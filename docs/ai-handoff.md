# AI Handoff — `ai_platform`

> 진행은 Karpathy 헌장 (CLAUDE.md) 을 따른다. 이 문서는 두 가지 모드:
> 1. **재개 노트**: 같은 사용자가 다른 세션에서 이어할 때 첫 명령까지.
> 2. **인계서**: 컨텍스트 없는 새 에이전트가 cold start.
> 둘 다 *git log* + *이 문서* + *`docs/claude-last-diff-summary.md`* 만 보면 충분해야 한다.

---

## 0. 한 줄 상태 (2026-05-24 11:50 KST)

**Phase 1: ✅ GREEN-LIGHT.** train_pipeline 이 KFP 에서 실제로 돌고, MLflow 에 `mlp v1, v2` 등록 (둘 다 5종 lineage 태그 miss=OK, staging alias=v2), MinIO 에 model artifact 적재. `deploy_canary` 의 *예상된 실패* 가 Phase 2 의 시작점.

**잔여 정리 + image diet 도 완료**: `compile-and-register.sh` idempotent rewrite, staging alias 실제 set 검증, trainer image **8.66 GB → 1.81 GB (5×↓)** 후 run-4 동일 green-light. Disk 86% → 78% (docker prune + completed pods cleanup).

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

매 commit body 에 *진실 검증* 증거 (compile 통과 / pod completed / MLflow 등록 / MinIO artifact / image size 등).

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
- `kfp-registry:5000/mlplatform/trainer:cpu` / `:latest` — **1.81GB**, python:3.10-slim + CPU torch + 11 패키지
- (옛 8.66GB image `:3c6df20` 는 prune 됨)

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

## 5. 발견된 진짜 버그 (3개) — 전부 commit 됨

| ID | 파일 | 증상 | Fix | 검증 |
|---|---|---|---|---|
| **C1** | `pipelines/components/pull_production_model.py` | `production_accuracy_out: OutputPath("String")` 이 소비자(`evaluate.baseline_accuracy: float`) 와 KFP 타입 불일치. compile 시 `InconsistentTypeException`. | NamedTuple 리턴으로 refactor (float 스칼라 + str). 호출부 `_out` suffix 제거. | compile OK 양쪽 파이프라인 (`026f8ad`) |
| **C2** | `pipelines/components/preprocess.py` | `np.savez_compressed(str_path, ...)` 가 `.npz` suffix 를 자동 추가 → KFP OutputPath (suffix 없음) 와 path 불일치 → train_mlp 가 `FileNotFoundError`. | `with open(path, "wb") as f: np.savez_compressed(f, ...)` — file handle 은 auto-suffix 안 붙음. | run-2 (3b5f00b5) 의 preprocess + train_mlp + evaluate 통과 (`d5da6ac`) |
| **C3** | `pipelines/components/common.py` + ConfigMap | mlflow client (boto3) 가 `MLFLOW_S3_ENDPOINT_URL` env 없으면 실제 AWS S3 로 가서 admin 자격 거부 → register_to_mlflow 가 `InvalidAccessKeyId`. | attach_platform_env 에 `MLFLOW_S3_ENDPOINT_URL` 추가, mlp-endpoints ConfigMap 에도 같은 키. | run-3 (fc33eb8a) register 통과 + MLflow v1 + MinIO artifact (`247a9bb`) |

---

## 6. Failing (의도된 — Phase 2 의 입구)

`deploy_canary` 가 항상 fail. 두 가지 원인:
1. `/templates/inferenceservice.yaml.j2`, `/templates/virtualservice.yaml.j2` 가 trainer image 의 fs 에 없음 (Dockerfile 이 templates 안 COPY 함). 컴포넌트 본문이 그 path 를 `Path("/templates/...").read_text()` 로 읽음 → `FileNotFoundError`.
2. KServe + Istio 가 클러스터에 없음 — 그래서 `kubectl apply` 가 됐어도 그 다음 단계가 의미 없음.

**Phase 2 의 시작점이 정확히 여기**: trainer image 에 templates 포함 + KServe/Istio 인스톨 + `serving` ns 준비 + `kserve-s3` ServiceAccount 의 S3 자격 secret. 그러면 `deploy_canary` 도 통과.

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

## 8. 다음 작업 (Phase 2 시작)

§8.B (Phase 1 잔여 정리) + image diet 는 이미 끝. 남은 path 는 **Phase 2 = serving stack**. 반나절~하루 분량. leaf007 의 RAM 11GB / Disk 30GB free 면 충분 (자원 어림은 별도 메모 참조).

### A.1 trainer image 에 templates COPY
`images/trainer/Dockerfile` 에 한 줄:
```dockerfile
COPY ../../serving /templates
```
또는 build context 를 repo root 로 바꾸고 명시. 그래야 `deploy_canary.py` 의 `Path("/templates/inferenceservice.yaml.j2").read_text()` 가 동작. 재빌드 + push 후 train_pipeline 재실행 — deploy_canary 까지 가는 *첫 번째 진실*.

### A.2 cert-manager (helm)
Istio 의 webhook TLS 발급용. 가장 가벼움 (~130MB).

### A.3 Istio (helm)
- `istio-base` + `istiod` + `istio-ingressgateway`
- demo profile 보다 minimal profile 권장 (RAM 절약)
- istiod 의 메모리 limit 을 명시적으로 (e.g. 512Mi) — 16GB 머신에 default(2Gi+) 면 부담

### A.4 KServe (Raw mode)
- KServe CRD + controller-manager
- `--set kserve.controller.deploymentMode=RawDeployment` 또는 ConfigMap 으로 명시
- Knative 의존성 제거가 핵심 — Raw 만 사용한다는 README 의 결정 반영

### A.5 serving ns + S3 자격
- `serving` namespace
- `kserve-s3` ServiceAccount + Secret (라파 MinIO 의 admin/ChangeMe!2026 또는 별도 user 발급)
- KServe 의 `InferenceService.spec.predictor.serviceAccountName` 가 이걸 참조

### A.6 mlp v2 를 production alias 로 + deploy_canary 검증
현재 `staging` alias=v2. production 으로 옮긴 후:
- `train_pipeline` 의 deploy_canary 단계까지 통과 (이번엔 KServe 가 있으니 *진짜* canary InferenceService 가 뜸)
- `kubectl -n serving get isvc mlp-canary` 가 Ready
- `curl mlp.mlplatform.local/v1/models/mlp:predict` 가 200 + 정상 prediction

이게 Phase 2 의 green-light. 그 후 Phase 3 (monitoring + drift → finetune 자동화) 으로.

---

## 9. 알려진 함정 / 다음에 또 만날 자리

1. ~~**trainer image 8.66GB**~~ → **1.81GB (e789c39)**. 해결됨.
2. ~~**`pipelines/compile-and-register.sh` 깨짐**~~ → **idempotent rewrite (ad89b13)**. 해결됨.
3. **AGENTS.md** — 사용자가 Codex 용으로 추가, untracked. commit 안 함 (사용자 의도 명확하지 않음).
4. **ConfigMap / Secret 셋업이 ad-hoc** — `kubeflow/mlp-endpoints`, `kubeflow/mlp-s3`, `mlops/pipeline-ids` 가 kubectl 한 명령씩 직접 apply 됨. 새 클러스터 bootstrap 에는 `scripts/apply-all.sh` 또는 manifest 가 필요. Phase 2 에서 같이 정리.
5. **`deploy_canary` 의 jinja template 로딩** — `Path("/templates/...").read_text()` 가 trainer image 안의 file 가정. Phase 2 의 §8.A.1 가 정확히 그 자리.
6. **KFP `search_model_versions().aliases` 가 빈 list** — search API limitation. 실제 alias 는 `get_model_version_by_alias` 또는 `get_registered_model().aliases` 로 확인 (검증됨).
7. **Disk 78%** — 정리 후도 빡빡함. *진짜 hog* 는 k3s containerd image cache (`/var/lib/rancher/k3s/...`) — `sudo crictl rmi --prune` 으로만 정리됨. Phase 2 진행 후 압박되면.

---

## 10. Hand-off rules (불변)

- 새 의존성은 PR 본문에 한 줄 정당화 (CLAUDE.md).
- `try/except` 는 외부 API/사용자 입력 경계만.
- 매 step 끝에 *실제 동작 증거* 첨부. 이 문서의 §4 같은 형식.
- 막히면 README 보다 *이 문서 + git log + 컴포넌트 코드* 가 진리원본.
- 컴포넌트 시그니처 변경은 양쪽 파이프라인 + register 의 호출부 모두 일관되게.
- KFP component 본문에서 외부 모듈 import 금지 — `pipelines/components/common.py` 는 *파이프라인 정의용* 헬퍼만 (`attach_platform_env`). 컴포넌트 본문은 함수 내부 import 만.
