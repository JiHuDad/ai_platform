#!/usr/bin/env bash
# Phase 2: Harbor / MinIO / MLflow / KFP / KServe.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1) Harbor =="
kubectl apply -f 10-harbor-cert.yaml
helm upgrade --install harbor harbor/harbor \
  -n harbor -f 10-harbor-values.yaml --wait --timeout 15m

echo "== 2) MinIO =="
helm upgrade --install minio minio/minio \
  -n minio -f 11-minio-values.yaml --wait --timeout 10m

echo "== 3) MinIO 클라이언트 부트스트랩 (버킷 확인) =="
kubectl -n minio run mc-bootstrap --rm -i --restart=Never \
  --image=minio/mc:latest -- /bin/sh -c '
    mc alias set local http://minio:9000 admin "ChangeMe!2026"
    for b in datasets mlflow-artifacts kfp-artifacts inference-logs reference-data drift-reports serving-manifests; do
      mc mb --ignore-existing local/${b}
      mc version enable local/${b} || true
    done
    mc ls local
  '

echo "== 4) MLflow =="
helm upgrade --install mlflow community-charts/mlflow \
  -n mlflow -f 12-mlflow-values.yaml --wait --timeout 10m

echo "== 5) Kubeflow Pipelines (standalone) =="
bash 13-kfp-install.sh

echo "== 6) KServe (Raw Deployment Mode) =="
helm upgrade --install kserve-crd oci://ghcr.io/kserve/charts/kserve-crd \
  -n kserve --create-namespace --wait
helm upgrade --install kserve oci://ghcr.io/kserve/charts/kserve \
  -n kserve -f 14-kserve-values.yaml --wait --timeout 10m
kubectl apply -f 14-kserve-gateway.yaml
kubectl apply -f 14-kserve-secrets.yaml

echo "[ok] Phase 2 complete."
kubectl -n harbor   get svc | grep harbor
kubectl -n minio    get pods
kubectl -n mlflow   get pods
kubectl -n kubeflow get pods | head
kubectl -n kserve   get pods
