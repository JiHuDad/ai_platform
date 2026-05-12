#!/usr/bin/env bash
# 부트스트랩 이후 실행: 파이프라인 RBAC, serving 매니페스트, monitoring rule,
# webhook/promote/rollback 컨트롤러 적용.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== KFP RBAC, serving 템플릿 ConfigMap =="
kubectl apply -f pipelines/kfp-rbac.yaml

echo "== Serving — destinationrule, inference-logger =="
kubectl apply -f serving/istio/destinationrule.yaml
kubectl apply -f serving/inference-logger.yaml

echo "== Monitoring — PrometheusRule, ServiceMonitor, Evidently CronJob =="
kubectl apply -f monitoring/alerts/kserve-servicemonitor.yaml
kubectl apply -f monitoring/alerts/mlp-drift.yaml
kubectl apply -f monitoring/evidently-job/cronjob.yaml

echo "== Controller — webhook + RBAC =="
kubectl apply -f controller/webhook/deploy.yaml

echo "[ok] platform glue applied. 이제 images/build-and-push.sh 후 pipelines/compile-and-register.sh 실행."
