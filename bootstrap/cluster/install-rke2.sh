#!/usr/bin/env bash
# RKE2 단일/HA 클러스터 부트스트랩.
# 사용: ./install-rke2.sh server   (첫 노드)
#       ./install-rke2.sh agent <SERVER_IP> <TOKEN>   (워커)
#       ./install-rke2.sh server <SERVER_IP> <TOKEN>  (추가 컨트롤플레인)
set -euo pipefail

ROLE="${1:?role required: server | agent}"
SERVER_IP="${2:-}"
TOKEN="${3:-}"

RKE2_VERSION="${RKE2_VERSION:-v1.29.4+rke2r1}"
CLUSTER_CIDR="${CLUSTER_CIDR:-10.42.0.0/16}"
SERVICE_CIDR="${SERVICE_CIDR:-10.43.0.0/16}"

install_common() {
  curl -sfL https://get.rke2.io | INSTALL_RKE2_VERSION="${RKE2_VERSION}" INSTALL_RKE2_TYPE="${1}" sh -
  mkdir -p /etc/rancher/rke2
}

write_config() {
  local cfg="/etc/rancher/rke2/config.yaml"
  cat > "${cfg}" <<EOF
cni: calico
cluster-cidr: ${CLUSTER_CIDR}
service-cidr: ${SERVICE_CIDR}
# kube-proxy 는 그대로, MetalLB L2 모드 사용
disable:
  - rke2-ingress-nginx        # Istio 가 ingress 담당
  - rke2-metrics-server       # kube-prometheus-stack 의 자체 metrics-server
write-kubeconfig-mode: "0644"
EOF
  if [[ -n "${SERVER_IP}" && -n "${TOKEN}" ]]; then
    cat >> "${cfg}" <<EOF
server: https://${SERVER_IP}:9345
token: ${TOKEN}
EOF
  fi
}

case "${ROLE}" in
  server)
    install_common server
    write_config
    systemctl enable --now rke2-server.service
    echo "[ok] rke2-server up. token: $(cat /var/lib/rancher/rke2/server/node-token)"
    echo "[ok] kubeconfig: /etc/rancher/rke2/rke2.yaml"
    ;;
  agent)
    [[ -z "${SERVER_IP}" || -z "${TOKEN}" ]] && { echo "agent role needs SERVER_IP and TOKEN"; exit 2; }
    install_common agent
    write_config
    systemctl enable --now rke2-agent.service
    ;;
  *)
    echo "unknown role: ${ROLE}"; exit 2;;
esac
