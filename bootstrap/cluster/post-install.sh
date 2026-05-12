#!/usr/bin/env bash
# RKE2 부트 후 공통 도구 설치 및 kubectl 별칭 설정.
set -euo pipefail

KUBECONFIG_SRC="/etc/rancher/rke2/rke2.yaml"
export KUBECONFIG="${KUBECONFIG_SRC}"

# kubectl/helm/mc 가 시스템에 없으면 받아둔다.
if ! command -v kubectl >/dev/null; then
  ln -sf /var/lib/rancher/rke2/bin/kubectl /usr/local/bin/kubectl
fi

if ! command -v helm >/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

if ! command -v mc >/dev/null; then
  curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc
  chmod +x /usr/local/bin/mc
fi

if ! command -v yq >/dev/null; then
  curl -fsSL https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -o /usr/local/bin/yq
  chmod +x /usr/local/bin/yq
fi

mkdir -p "${HOME}/.kube"
install -m 0600 "${KUBECONFIG_SRC}" "${HOME}/.kube/config"

# 헬름 리포 등록 (idempotent)
helm repo add metallb        https://metallb.github.io/metallb        || true
helm repo add longhorn       https://charts.longhorn.io               || true
helm repo add istio          https://istio-release.storage.googleapis.com/charts || true
helm repo add jetstack       https://charts.jetstack.io               || true
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts || true
helm repo add harbor         https://helm.goharbor.io                 || true
helm repo add minio          https://charts.min.io/                   || true
helm repo add community-charts https://community-charts.github.io/helm-charts || true   # mlflow
helm repo add kserve         oci://ghcr.io/kserve/charts              || true
helm repo update

# 네임스페이스 생성
for ns in metallb-system longhorn-system istio-system cert-manager monitoring \
          mlops mlflow kubeflow kserve serving harbor minio; do
  kubectl get ns "${ns}" >/dev/null 2>&1 || kubectl create ns "${ns}"
done

# istio 사이드카 자동 주입은 모든 ns 에서 기본 OFF.
# kserve Raw + 자체 메트릭 사용이므로 predictor pod 에는 사이드카 미사용.
for ns in serving mlops kserve kubeflow mlflow; do
  kubectl label ns "${ns}" istio-injection=disabled --overwrite
done

echo "[ok] post-install complete. namespaces & helm repos ready."
