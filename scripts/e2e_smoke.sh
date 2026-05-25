#!/usr/bin/env bash
# End-to-end smoke test. 단계별 그린라이트 검증.
# 전제: bootstrap/* 완료, images/build-and-push.sh 로 모든 이미지 Harbor 푸시 완료,
#       pipelines/compile-and-register.sh 로 KFP 파이프라인 업로드 완료,
#       controller/webhook/deploy.yaml 적용 완료,
#       monitoring/{alerts,evidently-job/cronjob}.yaml 적용 완료.

set -euo pipefail

STEP="${1:-all}"
MODEL="${MODEL:-mlp}"
NS="${NS:-serving}"
MINIO="kubectl -n minio exec -i deploy/minio -- mc"

gateway_url() {
  local ip
  ip="$(kubectl -n istio-system get svc istio-ingressgateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')"
  echo "http://${ip}"
}

run_step() {
  local name="$1"
  echo
  echo "======================================================"
  echo "▶ ${name}"
  echo "======================================================"
}

step_1_upload_dataset() {
  run_step "1) 데이터셋 업로드 → s3://datasets/demo/iris/$(date +%Y%m%d)-v1/"
  cd "$(dirname "$0")/../fixtures"
  python make-iris.py
  ${MINIO} cp /dev/stdin local/datasets/demo/iris/$(date +%Y%m%d)-v1/iris.csv < iris.csv
  ${MINIO} ls local/datasets/demo/iris/
}

step_2_run_training() {
  run_step "2) 학습 파이프라인 실행"
  python - <<PY
from kfp.client import Client
c = Client(host="http://localhost:8888")
exp = c.create_experiment("smoke")
import datetime
job = f"train-smoke-{int(datetime.datetime.utcnow().timestamp())}"
run = c.run_pipeline(
    experiment_id=exp.experiment_id,
    job_name=job,
    pipeline_id=open("/tmp/train_id").read().strip(),
    params={
        "dataset_uri": "s3://datasets/demo/iris/$(date +%Y%m%d)-v1/",
        "model_name": "${MODEL}",
        "baseline_accuracy": 0.0,
        "git_sha": "smoke",
        "triggered_by": "manual",
    },
)
print("submitted", run.run_id)
PY
  echo "↳ KFP UI 에서 run 성공 + MLflow 'staging' alias 확인 필요"
}

step_3_serve_curl() {
  run_step "3) Inference 엔드포인트 호출"
  EP="$(gateway_url)"
  echo "endpoint: ${EP}/v2/models/${MODEL}/infer"
  curl -fsSL \
    -H "Host: ${MODEL}.mlplatform.local" \
    -H 'Content-Type: application/json' \
    -d '{"inputs":[{"name":"input-0","shape":[1,4],"datatype":"FP32","data":[[5.1,3.5,1.4,0.2]]}]}' \
    "${EP}/v2/models/${MODEL}/infer" | tee /tmp/predict.json
}

step_4_drift_inject() {
  run_step "4) Drift 주입 (1000건 shifted payload)"
  EP="$(gateway_url)"
  python "$(dirname "$0")/perturb_inference.py" \
    --url "${EP}/v2/models/${MODEL}/infer" \
    --host-header "${MODEL}.mlplatform.local" \
    --n 1000 --shift 3.0 --qps 20
}

step_5_wait_evidently_and_alert() {
  run_step "5) Evidently CronJob 1회 강제 + drift 알림 firing 대기 (최대 35분)"
  kubectl -n monitoring create job --from=cronjob/evidently-${MODEL} evidently-now-$$
  kubectl -n monitoring wait --for=condition=complete job/evidently-now-$$ --timeout=300s
  echo "drift_score 확인:"
  kubectl -n monitoring port-forward svc/pushgateway 9091:9091 >/tmp/pf.log 2>&1 &
  PF=$!; sleep 3
  curl -s http://localhost:9091/metrics | grep mlp_drift_score
  kill ${PF} || true
}

step_6_observe_finetune_run() {
  run_step "6) Webhook 가 finetune 파이프라인 trigger 한 것 확인"
  kubectl -n kubeflow get workflows.argoproj.io -l pipeline/name=mlp-finetune --sort-by=.metadata.creationTimestamp | tail
  echo "↳ 최근 finetune run 1개가 Running/Succeeded 여야 함"
}

step_7_canary_progress() {
  run_step "7) Canary VS weight 변화 추적"
  for i in 1 2 3; do
    sleep 30
    kubectl -n ${NS} get vs ${MODEL} -o jsonpath='{.spec.http[0].route[*].weight}' ; echo
  done
}

step_8_rollback_chaos() {
  run_step "8) 카오스: canary 에 의도적 5xx 유발 → rollback-job 자동 실행"
  # 실제로는 alert 트리거를 위해 부하 + 의도적 500 응답 (transformer 에서 noisy) 가 필요.
  # 여기서는 Alertmanager API 로 직접 firing 알림을 보낸다 — webhook /rollback 경로 검증.
  kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-alertmanager 9093:9093 >/tmp/am.log 2>&1 &
  AM=$!; sleep 3
  curl -fsSL -X POST http://localhost:9093/api/v2/alerts \
    -H 'Content-Type: application/json' \
    -d "[{\"labels\":{\"alertname\":\"MLPHighErrorRate\",\"severity\":\"critical\",\"category\":\"serving_slo\",\"model\":\"${MODEL}\"},\"annotations\":{\"summary\":\"smoke chaos\"}}]"
  kill ${AM} || true
  sleep 20
  echo "rollback Job 결과:"
  kubectl -n ${NS} get jobs -l app=rollback --sort-by=.metadata.creationTimestamp | tail
  echo "VS weight 복구:"
  kubectl -n ${NS} get vs ${MODEL} -o jsonpath='{.spec.http[0].route[*].weight}' ; echo
}

step_9_lineage_check() {
  run_step "9) MLflow lineage 통합 확인"
  python - <<'PY'
import mlflow, os
mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"))
from mlflow.tracking import MlflowClient
c = MlflowClient()
for mv in c.search_model_versions("name='mlp'"):
    tags = {t.key: t.value for t in c.get_model_version(mv.name, mv.version).tags}
    needed = {"dataset_uri", "dataset_hash", "git_sha", "kfp_run_id", "triggered_by"}
    miss = needed - tags.keys()
    print(f"v{mv.version} aliases={mv.aliases} miss={miss or 'none'}")
PY
}

case "${STEP}" in
  1) step_1_upload_dataset ;;
  2) step_2_run_training ;;
  3) step_3_serve_curl ;;
  4) step_4_drift_inject ;;
  5) step_5_wait_evidently_and_alert ;;
  6) step_6_observe_finetune_run ;;
  7) step_7_canary_progress ;;
  8) step_8_rollback_chaos ;;
  9) step_9_lineage_check ;;
  all)
    step_1_upload_dataset
    step_2_run_training
    echo "↳ Training run 이 끝날 때까지 KFP UI 에서 확인 후 Enter:"; read -r _
    step_3_serve_curl
    step_4_drift_inject
    step_5_wait_evidently_and_alert
    echo "↳ Alert 30분 firing 대기 — Enter 후 다음:"; read -r _
    step_6_observe_finetune_run
    step_7_canary_progress
    step_8_rollback_chaos
    step_9_lineage_check
    echo
    echo "[ok] E2E smoke 완료"
    ;;
  *) echo "usage: $0 [1|2|3|4|5|6|7|8|9|all]"; exit 2;;
esac
