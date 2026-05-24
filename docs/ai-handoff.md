# AI Handoff — `ai_platform`

> 진행은 Karpathy 헌장 (CLAUDE.md) 을 따른다. 이 문서는 두 가지 모드:
> 1. **재개 노트**: 같은 사용자가 다른 세션에서 이어할 때 첫 명령까지.
> 2. **인계서**: 컨텍스트 없는 새 에이전트가 cold start.
> 둘 다 *git log* + *이 문서* + *`docs/claude-last-diff-summary.md`* 만 보면 충분해야 한다.

---

## 0. 한 줄 상태 (2026-05-24 16:35 KST)

**Phase 1: ✅ GREEN-LIGHT.** train_pipeline KFP 통과, MLflow 에 `mlp v1, v2` (둘 다 5종 lineage 태그 miss=OK, staging alias=v2), MinIO 에 model artifact 적재.

**Phase 2 (serving glue): ✅ GREEN-LIGHT.** run-7 의 **전체 KFP pipeline (data_ingest → register_to_mlflow → deploy_canary) 가 SUCCEEDED**. InferenceService `mlp-canary` + VirtualService `mlp` 가 serving ns 에 생성됨. MinIO 의 `serving-manifests/mlp/<ts>/` 에 yaml snapshot 적재. KServe storage-initializer 가 라파 MinIO 에서 model artifact pull 성공.

**Phase 2 의 마지막 자리 (모델 packaging) 만 미해결**: torchserve runtime 이 `.mar` archive + `config.properties` 를 기대. 우리 mlflow 아티팩트 (`state_dict.pt` + scripted `model.pt`) 는 그 형식 아님 → predictor pod CrashLoopBackOff. 별도 sub-step (§8 참조).

---

## 1. Environment topology

| Host | Role | 컴포넌트 |
|---|---|---|
| `leaf007` (amd64, 12C/16GB, 192.168.1.154) | k3s control + compute + dev workstation | k3s v1.29, KFP (`kubeflow` ns), `kfp-registry` (docker registry:2 on host) |
| `finux4` / Pi4 8GB (aarch64, 192.168.1.37) | Control-plane storage & tracking | Debian 13, Docker 26.1, MinIO `:9000/:9001`, **MLflow `:5001`**, registry `:5000`, 외장 Samsung SSD 870 EVO 233GB @ `/mnt/data` |

**도달성 검증값**: leaf007 ↔ Pi4 12~13ms. k3s pod 도 OK (busybox `wget` 검증).

**Registry resolution (sudo 로 1회 설정 완료)**:
- `/etc/hosts`: `127.0.0.1 kfp-registry`
- `/etc/rancher/k3s/registries.yaml`: `kfp-registry:5000` 을 insecure HTTP mirror
- `/etc/docker/daemon.json`: `insecure-registries: ["kfp-registry:5000"]`
- k3s + docker 재시작 완료.

**MinIO 자격 (라파)**: `admin` / `ChangeMe!2026`. env 의 `_FILE` 변수들은 파일 없어서 plain env fallback.

**버킷 (라파 MinIO)**:
- `mlflow-artifacts/` ← MLflow artifact root, model 산출물 적재됨
- `datasets/demo/iris/20260523-v1/iris.csv` ← Phase 1 fixture
- `tmp/` ← 무관, 2024 잔재

---

## 2. Commit history (이 세션들)

```
b12cbbd feat(trainer): bake kubectl v1.29.0 into image
3f057ca feat(trainer): bake jinja templates into image + fix deploy_canary base_name
6fb5b34 chore(claude): permission allowlist + deny — '삭제 빼고 자유롭게' 실현
a3c3987 docs: snapshot before Phase 2 — Phase 1 정리 + image diet 반영
e789c39 feat(trainer): CPU-only base — 8.66GB → 1.81GB (5×↓)
ad89b13 fix(scripts): compile-and-register 를 idempotent + venv-aware 로 다시 짬
f436289 docs: phase 1 green-light snapshot + session resume notes
247a9bb fix(env): inject MLFLOW_S3_ENDPOINT_URL so mlflow client points at Pi4 MinIO
d5da6ac fix(preprocess): np.savez_compressed → .npz auto-suffix 깨짐, file handle 로 우회
7bf308c chore(gitignore): exclude compile artifacts + generated fixture
54f66e0 fix(trainer): drop kfp from runtime requirements — resolves kubernetes conflict
23bf842 feat: inject MLflow/MinIO env into every KFP task via kfp-kubernetes
3c6df20 docs: ai-handoff + last-diff-summary for next agent (snapshot)
026f8ad fix: dead code, deprecated APIs, registry hostname, finetune type bug
a28091e docs: add CLAUDE.md — Karpathy-style working agreement
ad6907e feat: scaffold MLP MLOps platform end-to-end
d48ab48 chore: initialize repo
```

매 commit body 에 *진실 검증* 증거 (compile 통과 / pod completed / MLflow 등록 / MinIO artifact / image size / InferenceService Ready 상태 등).

---

## 3. Out-of-tree state (Pi4 + k3s)

### Pi4 컨테이너
| 이름 | 이미지 | 상태 | 의미 |
|---|---|---|---|
| `minio` | quay.io/minio/minio:latest | Up 10d+ | 라파 S3 |
| `registry` | registry:2 | Up 10d+ | (Phase 1 미사용 — leaf007 `kfp-registry` 가 KFP image source) |
| `mlflow` | ghcr.io/mlflow/mlflow:v2.16.2 | Up ~1h | tracking + artifact proxy |

### k3s 리소스
- `kubeflow/mlp-endpoints` ConfigMap — `MLFLOW_TRACKING_URI`, `MINIO_ENDPOINT`, `MLFLOW_S3_ENDPOINT_URL`
- `kubeflow/mlp-s3` Secret — `AWS_ACCESS_KEY_ID/SECRET`, `MINIO_ACCESS_KEY/SECRET`
- `mlops` namespace — `pipeline-ids` ConfigMap (`train=3732a01c-...`, `finetune=68d663f3-...`)
- KFP 의 `mlp-train`, `mlp-finetune` 두 파이프라인 업로드됨

### leaf007 trainer image
- `kfp-registry:5000/mlplatform/trainer:b12cbbd` / `:latest` — **1.86GB**, python:3.10-slim + CPU torch + 11 패키지 + `/templates/` (jinja) + `/usr/local/bin/kubectl` v1.29.0
- 이전 tag 들 (cpu, cpu-tpl, 3f057ca, 6fb5b34 등) registry 에 잔존

---

## 4. Phase 1 의 진실 (그린라이트 증거)

두 번의 green-light run:
- **run-3** `fc33eb8a-...`: 첫 green-light. → mlp v1 등록.
- **run-4** `c71fc385-...`: image diet 후 동일 결과 재현. → mlp v2 등록.

```
KFP DAG: data_ingest → preprocess → train_mlp → evaluate → register_to_mlflow → [deploy_canary FAIL — 예상]
              Completed   Completed   Completed   Completed       Completed

MLflow registry (서버 측 진리):
  registered_model: mlp
  aliases: {'staging': '2'}            # search_model_versions 의 mv.aliases 는 빈 list — search API limitation 확인됨
  v2  git_sha=smoke-cpu-image           kfp_run_id=train-smoke-4-cpu
  v1  git_sha=smoke-mlflow-s3-fix       kfp_run_id=train-smoke-3
  둘 다 같은 dataset_hash=39706f147590c33e..., 5종 lineage 태그 miss=OK

MinIO artifact (라파, 각 버전 마다):
  mlflow-artifacts/0/<run_uuid>/artifacts/model/meta.json       (197B)
  mlflow-artifacts/0/<run_uuid>/artifacts/model/model.pt        (46KiB, TorchScript)
  mlflow-artifacts/0/<run_uuid>/artifacts/model/state_dict.pt   (38KiB)
```

---

## 5. 발견된 진짜 버그 — 전부 commit 됨

| ID | 파일 | 증상 | Fix | 검증 |
|---|---|---|---|---|
| **C1** | `pipelines/components/pull_production_model.py` | `production_accuracy_out: OutputPath("String")` 이 소비자(`evaluate.baseline_accuracy: float`) 와 KFP 타입 불일치. compile 시 `InconsistentTypeException`. | NamedTuple 리턴으로 refactor (float 스칼라 + str). 호출부 `_out` suffix 제거. | compile OK 양쪽 파이프라인 (`026f8ad`) |
| **C2** | `pipelines/components/preprocess.py` | `np.savez_compressed(str_path, ...)` 가 `.npz` suffix 를 자동 추가 → KFP OutputPath (suffix 없음) 와 path 불일치 → train_mlp 가 `FileNotFoundError`. | `with open(path, "wb") as f: np.savez_compressed(f, ...)` — file handle 은 auto-suffix 안 붙음. | run-2 (3b5f00b5) 의 preprocess + train_mlp + evaluate 통과 (`d5da6ac`) |
| **C3** | `pipelines/components/common.py` + ConfigMap | mlflow client (boto3) 가 `MLFLOW_S3_ENDPOINT_URL` env 없으면 실제 AWS S3 로 가서 admin 자격 거부 → register_to_mlflow 가 `InvalidAccessKeyId`. | attach_platform_env 에 `MLFLOW_S3_ENDPOINT_URL` 추가, mlp-endpoints ConfigMap 에도 같은 키. | run-3 (fc33eb8a) register 통과 + MLflow v1 + MinIO artifact (`247a9bb`) |
| **C4** | `pipelines/components/deploy_canary.py` | jinja render 에 `base_name` 누락 → `mlp.yaml.j2` 의 `labels.app: {{ base_name }}` 가 Undefined → 빈 라벨 yaml → kubectl apply 거부. | `base_name=model_name` 인자 추가. | run-7 (b1632e43) 의 deploy_canary 통과 (`3f057ca`) |
| **C5** | `images/trainer/Dockerfile` (templates 부재) | deploy_canary 본문이 `/templates/*.yaml.j2` 를 read — image 에 없음. | build context 를 repo root 로 + `COPY serving/.../yaml.j2 /templates/` 두 줄. | run-7 에서 templates 로딩 통과 (`3f057ca`) |
| **C6** | `images/trainer/Dockerfile` (kubectl 부재) | deploy_canary 본문이 `subprocess.run(["kubectl", ...])` 호출 — slim base 에 kubectl 없음. | curl 로 kubectl v1.29.0 다운로드 + chmod. | run-6 에서 kubectl 동작 → CRD 부재 신호 (`b12cbbd`) |

---

## 6. ~~Failing (의도된)~~ → 해결됨

이전 핸드오프의 *deploy_canary 의 의도된 실패* (templates 부재 + KServe 부재) 가 **모두 해결**:
1. ✅ Templates image 안에 baked (C5, `3f057ca`)
2. ✅ base_name jinja Undefined (C4, `3f057ca`)
3. ✅ kubectl 바이너리 baked (C6, `b12cbbd`)
4. ✅ KServe + Istio + cert-manager 클러스터에 설치 (§9 참조)
5. ✅ serving ns + kserve-s3 SA + Pi4 자격 secret + HTTP gateway + RBAC (§10 참조)
6. ✅ `pipeline-runner` SA 에 serving ns 권한 (rolebinding `kfp-serving-deployer-default`)
7. ✅ serving-manifests bucket on 라파 MinIO

**Phase 2 의 진짜 미해결 자리는 모델 packaging** (§8 B.1 참조) — torchserve runtime 이 `.mar` archive 를 기대하는데 우리 mlflow artifact 는 raw state_dict + scripted .pt.

---

## 7. 내일/다음 세션 재개 — 첫 5분

### 7.1 환경 wake-up
```bash
cd /home/fall/dev/ai_platform
git status                           # clean 이어야 (commit 247a9bb 까지)
git log --oneline -5

# k3s 살아있는지
kubectl get nodes

# Pi4 컨테이너 살아있는지 (셋 다 Up X days)
ssh fall@192.168.1.37 'docker ps --format "table {{.Names}}\t{{.Status}}"'

# leaf007 → Pi4 도달
curl -s -o /dev/null -w "MinIO:%{http_code} " http://192.168.1.37:9000/minio/health/live
curl -s -o /dev/null -w "MLflow:%{http_code}\n" http://192.168.1.37:5001/health
```

### 7.2 KFP API 접근 (port-forward 재기동)
이전 세션의 port-forward 는 종료됨 (background process 가 셸 종료시 함께).
```bash
kubectl -n kubeflow port-forward svc/ml-pipeline 8888:8888 >/tmp/kfp-pf.log 2>&1 &
sleep 3 && curl -s http://localhost:8888/apis/v2beta1/pipelines | head -c 200
```

### 7.3 venv 활성화 (이 머신)
```bash
source .venv/bin/activate
python -c "import kfp; print(kfp.__version__)"   # 2.16.1
```

---

## 8. 다음 작업 (모델 packaging — Phase 2 의 마지막 sub-step)

Phase 2 의 §A.1~A.6 (인프라 설치 + glue) 는 *전부 완료*. 마지막 자리는 **모델 packaging**: torchserve 가 `.mar` archive + `config.properties` 를 기대하는데 우리는 raw state_dict + scripted .pt 만.

### B.1 옵션 — torch-model-archiver 로 `.mar` 생성 (가장 정직)

`train_mlp.py` 의 출력 디렉토리에 `.mar` 도 같이 저장:

```python
# train_mlp.py 끝에 추가
import subprocess
subprocess.run([
    "torch-model-archiver",
    "--model-name", "mlp",
    "--version", "1.0",
    "--serialized-file", str(out / "state_dict.pt"),
    "--model-file", str(out / "model_def.py"),   # MLP class 정의 — 새 파일 필요
    "--handler", "image_classifier",             # 또는 custom_handler.py
    "--export-path", str(out),
    "--force",
], check=True)
```

또한 `config.properties` 파일도 같이 생성:
```
inference_address=http://0.0.0.0:8080
management_address=http://0.0.0.0:8081
model_store=/mnt/models
load_models=mlp.mar
```

trainer image 에 `torch-model-archiver` 추가 필요 (`pip install torch-model-archiver`).

검증: predictor pod 의 `kserve-container` 가 Running, `mlp-canary` InferenceService URL 이 Ready=True.

### B.2 옵션 — InferenceService 의 runtime 변경

`mlp.yaml.j2` 의 `runtime: kserve-torchserve` → `kserve-mlserver` 또는 *custom python* 으로. mlserver-pytorch 가 `state_dict.pt` 직접 사용 가능한지 검토. 또는 *custom predictor container* (FastAPI 작성).

### B.3 옵션 — *지금 동작 그대로 Phase 3 진입*

Phase 2 의 glue 진실 (`deploy_canary` 통과, InferenceService 등록) 는 검증됨. predictor pod 의 Ready 는 *Phase 3 의 drift→finetune 루프 검증* 에는 영향 없음 (단 *실제 serving 호출* 은 안 됨). serving 호출 검증을 *별도 phase 2.5* 로 분리.

### 권장 순서: B.1

가장 정직한 path. mlflow 의 *모델 artifact 구조* 가 KServe + torchserve 의 *기대 구조* 와 맞추는 게 lineage 통일성 측면에서 옳다. handler 파일 한 개 + Dockerfile 한 줄 추가면 끝.

---

## 9. Phase 2 의 클러스터 install 명령 (재현용)

다음 세션 시작 시 *cluster 가 살아있으면* 이 명령들 재실행 필요 없음. *새 클러스터* 면 순서대로:

```bash
# 1) cert-manager (Prometheus servicemonitor 비활성화 — Phase 3 영역)
helm repo add jetstack https://charts.jetstack.io
helm upgrade --install cert-manager jetstack/cert-manager \
  -n cert-manager --create-namespace --version v1.14.5 \
  -f bootstrap/platform/02-cert-manager-values.yaml \
  --set prometheus.servicemonitor.enabled=false \
  --wait --timeout 5m

# 2) Istio (autoscale 1~2 로 줄임, LB IP 자동)
helm repo add istio https://istio-release.storage.googleapis.com/charts
helm upgrade --install istio-base istio/base -n istio-system --create-namespace \
  -f bootstrap/platform/03-istio-base-values.yaml --wait
helm upgrade --install istiod istio/istiod -n istio-system \
  -f bootstrap/platform/03-istiod-values.yaml \
  --set pilot.autoscaleMin=1 --set pilot.autoscaleMax=2 --wait
helm upgrade --install istio-ingressgateway istio/gateway -n istio-system \
  -f bootstrap/platform/03-istio-gateway-values.yaml \
  --set service.loadBalancerIP="" \
  --set autoscaling.minReplicas=1 --set autoscaling.maxReplicas=2 --wait

# 3) KServe — manifest 방식 (OCI helm chart 가 ghcr 에서 download 실패)
kubectl apply -f https://github.com/kserve/kserve/releases/download/v0.13.0/kserve.yaml
# kube-rbac-proxy image 가 gcr 에서 not found — quay 로 patch
kubectl -n kserve set image deployment/kserve-controller-manager \
  kube-rbac-proxy=quay.io/brancz/kube-rbac-proxy:v0.14.0
kubectl -n kserve rollout status deployment/kserve-controller-manager --timeout=3m
kubectl apply -f https://github.com/kserve/kserve/releases/download/v0.13.0/kserve-cluster-resources.yaml

# 4) serving ns + Pi4-자격 secret + kserve-s3 SA + HTTP-only gateway
# (handoff §10 의 yaml — 인라인 apply)

# 5) RBAC
kubectl apply -f pipelines/kfp-rbac.yaml
kubectl -n serving create rolebinding kfp-serving-deployer-default \
  --role=kfp-serving-deployer \
  --serviceaccount=kubeflow:pipeline-runner

# 6) serving-manifests bucket (deploy_canary 의 mc cp 대상)
docker run --rm --network host --entrypoint sh minio/mc -c "
  mc alias set pi http://192.168.1.37:9000 admin 'ChangeMe!2026' >/dev/null
  mc mb --ignore-existing pi/serving-manifests
"
```

---

## 10. 인라인 apply 한 manifest (재현용 yaml)

### serving ns 의 kserve-s3 SA + Pi4-자격 secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: minio-s3-creds
  namespace: serving
  annotations:
    serving.kserve.io/s3-endpoint: 192.168.1.37:9000
    serving.kserve.io/s3-usehttps: "0"
    serving.kserve.io/s3-region: us-east-1
    serving.kserve.io/s3-useanoncredential: "false"
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: admin
  AWS_SECRET_ACCESS_KEY: "ChangeMe!2026"
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: kserve-s3
  namespace: serving
secrets:
  - name: minio-s3-creds
```

### HTTP-only kserve-gateway (cert-manager ClusterIssuer 없으니 HTTPS 빼고)

```yaml
apiVersion: networking.istio.io/v1beta1
kind: Gateway
metadata:
  name: kserve-gateway
  namespace: istio-system
spec:
  selector:
    istio: ingressgateway
  servers:
    - port: { number: 80, name: http, protocol: HTTP }
      hosts: ["*.mlplatform.local", "mlp.mlplatform.local"]
```

---

## 11. 알려진 함정 / 다음에 또 만날 자리

1. ~~trainer image 8.66GB~~ → **1.86GB** (e789c39 + b12cbbd). 해결.
2. ~~compile-and-register.sh 깨짐~~ → idempotent rewrite (ad89b13). 해결.
3. ~~deploy_canary 의 templates 로딩~~ → image 에 baked (3f057ca). 해결.
4. **AGENTS.md** — 사용자가 Codex 용으로 추가, untracked. commit 안 함.
5. **ad-hoc 클러스터 셋업** — `kubeflow/mlp-endpoints`, `kubeflow/mlp-s3`, `mlops/pipeline-ids`, `serving/{minio-s3-creds, kserve-s3}`, `istio-system/kserve-gateway`, RBAC 들 다 kubectl 한 명령씩. §9 + §10 이 재현 명령. 향후 `scripts/apply-all.sh` 로 통합 권장.
6. **KFP `search_model_versions().aliases` 가 빈 list** — search API limitation. 실제 alias 는 `get_model_version_by_alias` 또는 `get_registered_model().aliases` 로 (검증됨).
7. **Disk 78%** — *진짜 hog* 는 k3s containerd image cache (`/var/lib/rancher/k3s/...`) — `sudo crictl rmi --prune` 으로만 정리됨. KServe + Istio + cert-manager image 추가로 더 늘었음. 다음 압박되면 청소.
8. **KFP default SA = `pipeline-runner`** (kfp-rbac.yaml 이 만든 `kfp-pipeline-runner` 와 *다른 이름*). 새 RoleBinding `kfp-serving-deployer-default` 가 진짜 default SA 에 권한 부여. 다음 컴포넌트가 serving ns 의 다른 리소스 만들 때 동일 패턴.
9. **kube-rbac-proxy image** — KServe v0.13.0 manifest 의 `gcr.io/kubebuilder/kube-rbac-proxy:v0.13.1` 가 *not found* (GCR 에서 옮김). `kubectl set image` 로 `quay.io/brancz/kube-rbac-proxy:v0.14.0` 로 patch. 새 클러스터 셋업 시 동일 patch 필요.
10. **KServe OCI helm chart download 실패** — `oci://ghcr.io/kserve/charts/kserve-crd` 가 download error. manifest 방식 (`kubectl apply -f release.yaml`) 우회.
11. **cert-manager values 의 `prometheus.servicemonitor.enabled: true`** — Prometheus operator (Phase 3 영역) 없으면 install 실패. `--set prometheus.servicemonitor.enabled=false` override.
12. **istio-gateway values 의 `loadBalancerIP: 10.10.50.201`** — MetalLB 가정. k3s servicelb 에서는 `--set service.loadBalancerIP=""` override. (`--set ...=null` 은 schema 거부.)
13. **kserve-gateway 의 HTTPS+cert-manager** — `ClusterIssuer/mlplatform-ca` 가 없어서 cert 발급 안 됨. Phase 2 검증용으로 HTTPS 부분 제거 + HTTP only. production 셋업에선 ClusterIssuer 추가 후 원본 yaml 사용.

---

## 12. Hand-off rules (불변)

- 새 의존성은 PR 본문에 한 줄 정당화 (CLAUDE.md).
- `try/except` 는 외부 API/사용자 입력 경계만.
- 매 step 끝에 *실제 동작 증거* 첨부. 이 문서의 §4 같은 형식.
- 막히면 README 보다 *이 문서 + git log + 컴포넌트 코드* 가 진리원본.
- 컴포넌트 시그니처 변경은 양쪽 파이프라인 + register 의 호출부 모두 일관되게.
- KFP component 본문에서 외부 모듈 import 금지 — `pipelines/components/common.py` 는 *파이프라인 정의용* 헬퍼만 (`attach_platform_env`). 컴포넌트 본문은 함수 내부 import 만.
