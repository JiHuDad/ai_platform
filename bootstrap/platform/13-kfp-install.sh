#!/usr/bin/env bash
# Kubeflow Pipelines standalone 설치 — 전체 Kubeflow 가 아닌 KFP 만.
# https://www.kubeflow.org/docs/components/pipelines/operator-guides/installation/
set -euo pipefail

KFP_VERSION="${KFP_VERSION:-2.2.0}"
NS="${NS:-kubeflow}"

kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/cluster-scoped-resources?ref=${KFP_VERSION}"
kubectl wait --for condition=established --timeout=120s crd/applications.app.k8s.io
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/env/platform-agnostic?ref=${KFP_VERSION}"

# KFP 기본 metadata-store/MinIO 컴포넌트는 사용하지 않고 클러스터 MinIO 로 교체.
kubectl -n "${NS}" apply -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: kfp-launcher
  namespace: kubeflow
data:
  defaultPipelineRoot: s3://kfp-artifacts/
  bucketName: kfp-artifacts
  ObjectStoreConfig: |
    endpoint: minio.minio.svc.cluster.local:9000
    region: us-east-1
    disableSSL: true
    forcePathStyle: true
EOF

# KFP 가 MinIO 접근 시 사용할 credential.
kubectl -n "${NS}" create secret generic mlpipeline-minio-artifact \
  --from-literal=accesskey=kfp-sa \
  --from-literal=secretkey='ChangeMe!Kfp2026' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "${NS}" rollout status deploy/ml-pipeline           --timeout=300s
kubectl -n "${NS}" rollout status deploy/ml-pipeline-ui        --timeout=300s
kubectl -n "${NS}" rollout status deploy/metadata-grpc-deployment --timeout=300s
echo "[ok] KFP standalone installed in namespace ${NS}"
