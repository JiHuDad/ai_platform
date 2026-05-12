#!/usr/bin/env bash
# Phase 1: 클러스터 네트워킹/스토리지/관측 부트스트랩.
# 전제: bootstrap/cluster/install-rke2.sh + post-install.sh 완료.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1) MetalLB =="
helm upgrade --install metallb metallb/metallb \
  -n metallb-system --create-namespace --wait
kubectl apply -f 00-metallb.yaml

echo "== 2) Longhorn =="
# longhorn-storage 라벨이 붙은 노드가 1개 이상이어야 한다.
kubectl get nodes -l longhorn-storage=true -o name | grep -q . || {
  echo "[warn] no node has label longhorn-storage=true. Labeling all worker nodes."
  for n in $(kubectl get nodes -o name); do
    kubectl label "${n}" longhorn-storage=true --overwrite
  done
}
helm upgrade --install longhorn longhorn/longhorn \
  -n longhorn-system -f 01-longhorn-values.yaml --wait --timeout 10m

echo "== 3) cert-manager =="
helm upgrade --install cert-manager jetstack/cert-manager \
  -n cert-manager --version v1.14.5 -f 02-cert-manager-values.yaml --wait
kubectl apply -f 02-cluster-issuer.yaml

echo "== 4) Istio (base + istiod + ingress gateway) =="
helm upgrade --install istio-base istio/base \
  -n istio-system -f 03-istio-base-values.yaml --wait
helm upgrade --install istiod istio/istiod \
  -n istio-system -f 03-istiod-values.yaml --wait
helm upgrade --install istio-ingressgateway istio/gateway \
  -n istio-system -f 03-istio-gateway-values.yaml --wait

echo "== 5) kube-prometheus-stack + pushgateway =="
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring -f 04-kube-prometheus-stack-values.yaml --wait --timeout 15m
kubectl apply -f 04-pushgateway.yaml

echo "[ok] Phase 1 complete."
kubectl -n metallb-system   get pods
kubectl -n longhorn-system  get pods | head
kubectl -n istio-system     get svc istio-ingressgateway
kubectl -n monitoring       get pods | head
