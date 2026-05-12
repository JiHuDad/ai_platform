#!/usr/bin/env bash
# 파이프라인 컴파일 후 KFP 에 업로드. 결과 pipeline_id 를 ConfigMap 으로 노출 (webhook 에서 참조).
set -euo pipefail
cd "$(dirname "$0")/.."

KFP_HOST="${KFP_HOST:-http://localhost:8888}"          # 사용 시 kubectl port-forward 또는 in-cluster URL
NS="${NS:-mlops}"

python -m pipelines.train_pipeline
python -m pipelines.finetune_pipeline

TRAIN_ID=$(kfp pipeline upload -p mlp-train    pipelines/train_pipeline.yaml    | awk '{print $NF}' || true)
FT_ID=$(   kfp pipeline upload -p mlp-finetune pipelines/finetune_pipeline.yaml | awk '{print $NF}' || true)

[ -n "${TRAIN_ID}" ] && [ -n "${FT_ID}" ] || { echo "[err] upload failed"; exit 1; }

kubectl -n "${NS}" create configmap pipeline-ids \
  --from-literal=train="${TRAIN_ID}" \
  --from-literal=finetune="${FT_ID}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "[ok] train=${TRAIN_ID} finetune=${FT_ID} written to ConfigMap pipeline-ids"
