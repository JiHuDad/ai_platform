# MLP MLOps 플랫폼 부트스트랩

> on-prem K8s **신규 구축** 가정. 모든 명령은 컨트롤플레인 노드 또는 kubeconfig 가 셋업된 워크스테이션에서 실행.

## 0. 사전 요구사항
- Ubuntu 22.04+ 서버 3대 이상 (컨트롤플레인 1+ / 워커 2+) — dev 면 단일 노드 가능
- 사내 LAN 에 IP 풀 (MetalLB) 확보 — 예: `10.10.50.200-250`
- DNS: `*.mlplatform.local` 가 위 풀의 ingress IP 로 해석되도록 사내 DNS/hosts 등록

## 1. 클러스터 부트스트랩
```bash
# 컨트롤플레인 #1
sudo ./cluster/install-rke2.sh server
# 토큰 출력 확인 후, 나머지 노드:
sudo TOKEN=<token> ./cluster/install-rke2.sh server <cp1-ip> <token>      # 추가 CP
sudo TOKEN=<token> ./cluster/install-rke2.sh agent  <cp1-ip> <token>      # 워커

# 도구 설치
sudo ./cluster/post-install.sh
```

## 2. 플랫폼 컴포넌트
```bash
./platform/install-phase1.sh   # MetalLB / Longhorn / Istio / cert-manager / kube-prometheus-stack
./platform/install-phase2.sh   # Harbor / MinIO / MLflow / KFP / KServe (Raw + Istio)
```

## 3. 검증 (Quick smoke)
```bash
# 외부 진입점
kubectl -n istio-system get svc istio-ingressgateway -o wide

# MLflow UI
curl -kfsSL https://mlflow.mlplatform.local/ | head

# MinIO 버킷
kubectl -n minio exec deploy/minio -- mc ls local

# KFP UI 포트포워딩 (dev)
kubectl -n kubeflow port-forward svc/ml-pipeline-ui 8080:80

# KServe CRD
kubectl get crd inferenceservices.serving.kserve.io
```

## 4. 환경 변수 변경 포인트
| 파일 | 변경 항목 |
|------|----------|
| `platform/00-metallb.yaml`        | IPAddressPool 대역 |
| `platform/03-istio-gateway-values.yaml` | `loadBalancerIP` |
| `platform/10-harbor-values.yaml`  | `expose.loadBalancer.IP`, 비밀번호 |
| `platform/11-minio-values.yaml`   | 비밀번호, replicas |
| `platform/12-mlflow-values.yaml`  | DB/MinIO credential |
| `platform/14-kserve-secrets.yaml` | MinIO credential |

> 비밀값은 부트스트랩 후 즉시 **SealedSecrets** 또는 외부 KMS 로 교체할 것.
