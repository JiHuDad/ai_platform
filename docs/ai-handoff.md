# AI Handoff — `ai_platform` Phase 1

이 문서는 다른 코딩 에이전트가 *현재 세션의 컨텍스트 없이도* Phase 1 을 이어서 끝낼 수 있도록 작성된 인계서. CLAUDE.md 의 카파시 원칙을 따른다.

---

## 1. Objective (한 단락)

`train_pipeline.py` 가 KFP 에서 실행되어 **MinIO 의 iris 데이터셋 → 학습 → MLflow 등록까지 한 번이라도 통과한다** 는 진실을 만든다. 그린라이트 = MLflow UI (http://192.168.1.37:5001) 에 `mlp` v1 이 등장하고 5종 lineage 태그 (`dataset_uri`, `dataset_hash`, `git_sha`, `kfp_run_id`, `triggered_by`) 가 전부 채워져 있을 것.

`deploy_canary` 컴포넌트는 KServe 가 없으므로 **의도된 실패** — 그 직전 `register_to_mlflow` 까지의 PASS 가 Phase 1 의 종료 조건. Phase 2 (serving) / Phase 3 (자동화 루프) 는 별도.

---

## 2. Environment topology (현재 시점)

| Host | Role | 주요 컴포넌트 |
|---|---|---|
| `leaf007` (amd64, 12C/16GB) | k3s control + compute | k3s v1.29, KFP (`kubeflow` ns, mysql + ml-pipeline + seaweedfs), `kfp-registry:5000` (docker registry:2) |
| `finux4` / `192.168.1.37` (Pi4 8GB, aarch64) | Control plane storage | Debian 13, Docker 26.1, MinIO `:9000/:9001`, **MLflow `:5001`**, 외장 Samsung SSD 870 EVO 233GB @ `/mnt/data` |

**도달성 (검증됨)**: leaf007 → 라파 12~13ms, k3s pod → 라파 OK.

**MinIO 자격**: `admin` / `ChangeMe!2026` (env 의 `_FILE` 변수들이 가리키는 파일은 없어서 plain env 로 동작).

**버킷 (현재)**: `mlflow-artifacts`, `datasets`. 둘 다 비어있음.

---

## 3. Files changed (이 세션)

**Repo 내 코드 변경: 없음.** `git status` 클린, 마지막 커밋은 `a28091e docs: add CLAUDE.md`.

**신규 작성 문서**:
- `docs/ai-handoff.md` (이 파일)
- `docs/claude-last-diff-summary.md`

---

## 4. Infrastructure changed (Pi4)

이전 세션 (10일 전) 에 이미 존재:
- `minio` 컨테이너 (10일 가동), `registry:2` 컨테이너 (10일 가동)
- `/mnt/data/{minio,registry,backup}` 디렉토리 구조

이번 세션에 추가:
- MinIO 버킷 `mlflow-artifacts`, `datasets` 생성 (`mc mb`)
- `/mnt/data/mlflow/` 디렉토리 생성 (SQLite backend store 용)
- `mlflow` 컨테이너 신규: `ghcr.io/mlflow/mlflow:v2.16.2`, port 5001:5000, restart `unless-stopped`, args:
  ```
  mlflow server --host 0.0.0.0 --port 5000 \
    --backend-store-uri sqlite:////mlflow/mlflow.db \
    --default-artifact-root s3://mlflow-artifacts/
  ```
  env: `MLFLOW_S3_ENDPOINT_URL=http://192.168.1.37:9000`, `AWS_ACCESS_KEY_ID=admin`, `AWS_SECRET_ACCESS_KEY=ChangeMe!2026`

검증된 응답: `curl http://192.168.1.37:5001/version` → `2.16.2`.

---

## 5. Key decisions (왜)

| 결정 | 근거 |
|---|---|
| **README 의 RKE2 + 풀스택 무시, k3s 유지** | k3s 가 47일 안정 가동중 + KFP 가 이미 살아있음. 갈아엎는 비용 > Phase 1 가치. |
| **Harbor 미설치, leaf007 `kfp-registry:5000` 사용** | Harbor 단독 1GB+ RAM. 로컬 registry 가 *이미 떠있고* trainer image 한 개 push 가 목표라 RBAC 불필요. |
| **MinIO/MLflow 를 Pi4 에 분리** | leaf007 (16GB) 가 phase 3 까지 가면 빡빡함이 *물리적으로 증명* 됨. control-plane (state) ↔ compute-plane (k3s) 분리가 정직. |
| **MLflow 포트 5001 (5000 아님)** | Pi4 의 registry:2 가 이미 5000 점유. 기존 인프라 안 건드림. |
| **KFP 내장 seaweedfs 미사용, Pi4 MinIO 사용** | 진리원본 하나. lineage 태그의 `dataset_uri` 가 Pi4 MinIO 한 곳을 가리키게 통일. |
| **Phase 1 에서 `deploy_canary` 의도된 실패 허용** | `if skip_deploy` 같은 옵션 추가 = "필요해진 다음에만" 원칙 위반. 실패가 KServe 부재의 정직한 신호. |

---

## 6. Known bugs (사전 분석에서 잡힘 — step 6 에서 일괄 수정)

### B1. Dead code (확정)
**파일**: `controller/webhook/main.py:70`
```python
params = {p.name: p.value for p in (r.run_details.pipeline_runtime.workflow_manifest or []) if False}
```
`if False` 라 항상 빈 dict. `params` 변수는 그 후 사용되지도 않음. **삭제**.

### B2. `dir()` 로 로컬 변수 존재 체크 (악취)
**파일**: `controller/canary-job/promote.py:141`
```python
log.info("MLflow alias production=%s (previous→%s)", NEW_VERSION,
         getattr(cur_prod, "version", "none") if "cur_prod" in dir() else "none")
```
`cur_prod` 가 try 블록에서만 binding 됨. **수정**: try 전에 `cur_prod = None` 초기화 후 `cur_prod.version if cur_prod else "none"`.

### B3. pandas `ffill(method=)` deprecated
**파일**: `monitoring/evidently-job/run.py:87`
```python
cur = cur.reindex(columns=feature_cols).fillna(method="ffill").fillna(0.0)
```
pandas 2.x 에서 deprecated. **수정**: `.ffill().fillna(0.0)`.

### B4. Lineage 모호성
**파일**: `pipelines/finetune_pipeline.py` (register_to_mlflow 호출부)
`dataset_uri=ds.outputs["new_dataset_uri_out"]` 만 들어가서 *base 가 어디서 왔는지* lineage 추적 불가. **수정**: register 호출의 `dataset_uri` 를 `f"{base_dataset_uri}|{new_uri}"` 또는 별도 태그 `base_dataset_uri` 추가. 단순한 쪽으로 가면 — base_dataset_uri 를 별도 태그로 register_to_mlflow 시그니처에 추가. *조심*: 컴포넌트 시그니처 변경은 train_pipeline 도 같이 업데이트해야 함.

### B5. 환경 의존 endpoint 가 컴포넌트에 hardcode
**파일**: 여러 컴포넌트의 `base_image="harbor.mlplatform.local/mlplatform/trainer:latest"`
Harbor 안 씀. **수정**: `kfp-registry:5000/mlplatform/trainer:latest` 로 일괄 sed. (이건 step 8 에서 처리, B1~B4 와 같이 묶어도 OK.)

---

## 7. Failing / not-yet-attempted commands

이 세션에서 *실제로 실패한* 명령:
- `ssh -o BatchMode=yes fall@192.168.1.37` (해결됨: leaf007 에 ed25519 키 생성 후 라파 authorized_keys 에 등록 완료)

아직 *실행되지 않은* 핵심 검증 명령:
- `python -c "from pipelines.train_pipeline import train_pipeline; from kfp.compiler import Compiler; Compiler().compile(train_pipeline, '/tmp/t.yaml')"` — KFP compile sanity
- `pipelines/compile-and-register.sh` — 컴파일 + KFP 업로드
- `scripts/e2e_smoke.sh 1` — iris 업로드 단계
- `scripts/e2e_smoke.sh 2` — training run

위 4개 중 어느 하나라도 깨지면 *그 자리에서 fix 후 같은 명령으로 재실행* — 카파시 식. 우회 옵션 추가 금지.

**예상되는 깨짐 자리** (사전 점검에서 추정):
- `pipelines/components/deploy_canary.py` 가 `/templates/inferenceservice.yaml.j2` 를 읽음. trainer image 안에 그 파일이 들어있어야 함 → `images/trainer/Dockerfile` 확인 필요.
- `train_mlp.py` 가 `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` env 를 기대 (`base_checkpoint_uri` 가 있을 때만). Phase 1 의 train 경로 (`base_checkpoint_uri=""`) 에선 안 타지만 env 자체는 모든 컴포넌트에 주입 권장.

---

## 8. Exact next steps (그대로 실행 가능)

### Step 6 — Quick fix 4개 + endpoint sed 한 commit

```bash
cd /home/fall/dev/ai_platform

# B1
sed -i '/r.run_details.pipeline_runtime.workflow_manifest or \[\]) if False/,/단순화: run name/{
  /params = /d
}' controller/webhook/main.py
# ↑ 위가 위험하면 수동 편집 권장 — 정확히 main.py 의 70번 줄과 그 위 주석 정리.

# B2 — 수동 편집 권장 (파일이 작음)
$EDITOR controller/canary-job/promote.py  # line 141 근처

# B3
sed -i 's/\.fillna(method="ffill")/.ffill()/' monitoring/evidently-job/run.py

# B4 — register_to_mlflow.py 시그니처에 base_dataset_uri 추가하고
#       finetune_pipeline.py 호출부에서 base_dataset_uri 도 넘김.
#       단순 한 줄 추가가 안 되면 lineage 태그를 dataset_uri 안에
#       파이프로 합쳐 넣는 쪽 (덜 정직하지만 시그니처 변경 없음).

# B5 — harbor → 로컬 registry 일괄 변경
grep -rln 'harbor.mlplatform.local' pipelines/ controller/ monitoring/ images/ \
  | xargs sed -i 's|harbor.mlplatform.local/mlplatform/|kfp-registry:5000/mlplatform/|g'
git grep harbor.mlplatform.local  # 잔재 0개여야 함

# verify
python -c "from pipelines.train_pipeline import train_pipeline; \
           from kfp.compiler import Compiler; \
           Compiler().compile(train_pipeline, '/tmp/t.yaml'); \
           print('compile OK')"

git add -A
git commit -m "fix: dead code, deprecated pandas, registry hostname

- controller/webhook/main.py: remove dead 'if False' params dict
- controller/canary-job/promote.py: initialize cur_prod=None, drop dir() trick
- monitoring/evidently-job/run.py: ffill(method=) → ffill()
- pipelines/finetune_pipeline.py: add base_dataset_uri to lineage
- harbor.mlplatform.local → kfp-registry:5000 (Harbor 미사용)

verify: python -c '... Compiler().compile(...)' → 'compile OK'"
```

### Step 7 — Trainer image 빌드 + push

```bash
cd /home/fall/dev/ai_platform
# build-and-push.sh 가 어떻게 짜여있는지 먼저 본 후 실행.
# 만약 그 스크립트가 harbor 를 가정하면 sed 로 endpoint 만 교체 가능.
cat images/build-and-push.sh

# 권장 변수
export REGISTRY=kfp-registry:5000
export TAG=v0.1.0
bash images/build-and-push.sh   # 또는 손으로 docker build + push

# 검증
docker pull kfp-registry:5000/mlplatform/trainer:${TAG}
```

### Step 8 — KFP 가 라파 MinIO + MLflow 보도록 ConfigMap/Secret

```bash
# k3s 의 kubeflow ns 에 trainer pod 가 받을 env 주입.
# 카파시 식: ConfigMap 하나 + Secret 하나, dispatch 없이.
kubectl -n kubeflow create configmap mlp-endpoints \
  --from-literal=MLFLOW_TRACKING_URI=http://192.168.1.37:5001 \
  --from-literal=MINIO_ENDPOINT=http://192.168.1.37:9000 \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n kubeflow create secret generic mlp-s3 \
  --from-literal=AWS_ACCESS_KEY_ID=admin \
  --from-literal=AWS_SECRET_ACCESS_KEY='ChangeMe!2026' \
  --from-literal=MINIO_ACCESS_KEY=admin \
  --from-literal=MINIO_SECRET_KEY='ChangeMe!2026' \
  --dry-run=client -o yaml | kubectl apply -f -
```

컴포넌트가 이 env 를 *어떻게 받을지* 는 KFP v2 의 `dsl.component(... base_image=..., packages_to_install=...)` 안에서 직접 env 주입은 한정적. 가장 단순한 길: trainer image 의 ENTRYPOINT 에서 컴포넌트 함수 안의 `os.environ` 으로 읽도록 두고, KFP `set_env_variable` 또는 KFP pod-default 를 활용. *단기 hack*: `pipelines/kfp-rbac.yaml` 옆에 PodDefault (또는 patch) 를 두어 모든 컴포넌트 pod 에 env 자동 주입.

### Step 9 — iris dataset 업로드

```bash
cd /home/fall/dev/ai_platform/fixtures
python make-iris.py   # iris.csv 생성

# mc 로 라파 MinIO 에 업로드
docker run --rm --network host \
  -v "$PWD:/work" \
  minio/mc sh -c "
    mc alias set pi http://192.168.1.37:9000 admin 'ChangeMe!2026' &&
    mc cp /work/iris.csv pi/datasets/demo/iris/$(date +%Y%m%d)-v1/iris.csv
  "
docker run --rm --network host minio/mc \
  ls pi/datasets/demo/iris/
```

### Step 10 — train_pipeline compile + 업로드 + 첫 run

```bash
cd /home/fall/dev/ai_platform
bash pipelines/compile-and-register.sh   # 내부 명령을 한 번 본 후 실행

# KFP UI port-forward (다른 터미널)
kubectl -n kubeflow port-forward svc/ml-pipeline-ui 8080:80

# 또는 SDK 로 run 제출
python - <<PY
from kfp.client import Client
c = Client(host="http://localhost:8888")  # port-forward 필요할 수 있음
exp = c.create_experiment("smoke")
run = c.run_pipeline(
    experiment_id=exp.experiment_id,
    job_name="train-smoke-1",
    pipeline_id=open("/tmp/train_id").read().strip(),
    params={
        "dataset_uri": "s3://datasets/demo/iris/$(date +%Y%m%d)-v1/",
        "model_name": "mlp",
        "baseline_accuracy": 0.0,
        "git_sha": "smoke",
        "triggered_by": "manual",
    },
)
print("submitted:", run.run_id)
PY
```

### Step 11 — Green-light 검증

```bash
# MLflow 에 mlp v1 + 5종 태그 있는지
python - <<'PY'
import mlflow
mlflow.set_tracking_uri("http://192.168.1.37:5001")
from mlflow.tracking import MlflowClient
c = MlflowClient()
needed = {"dataset_uri", "dataset_hash", "git_sha", "kfp_run_id", "triggered_by"}
for mv in c.search_model_versions("name='mlp'"):
    tags = {t.key: t.value for t in c.get_model_version(mv.name, mv.version).tags}
    miss = needed - tags.keys()
    print(f"v{mv.version} aliases={mv.aliases} miss={miss or 'OK'}")
PY

# MinIO 에 artifact 떨어졌는지
docker run --rm --network host minio/mc \
  ls -r --summarize pi/mlflow-artifacts/ | tail -5
```

**그린라이트**: `miss=OK` 가 한 줄 이상 + MinIO 에 `model.pt`, `state_dict.pt`, `meta.json` 흔적.

`deploy_canary` 단계 실패 (KServe 없음) 는 *예상된 결과*. KFP UI 의 run graph 에서 `register_to_mlflow` 까지 초록색이면 종료.

---

## 9. Out-of-scope (Phase 1 에선 *건드리지 않음*)

- KServe / Istio / cert-manager 설치
- Evidently CronJob 배포
- `ml-webhook` Deployment 적용
- Prometheus rule, alertmanager 라우팅
- `finetune_pipeline.py` 의 run
- `images/{evidently,webhook,promote,rollback}` 이미지 빌드

이들은 Phase 2 / 3 의 영역. 한 번에 다 손대면 디버깅 표면이 폭발한다 (카파시: "scope creep is the silent killer").

---

## 10. Verification gates (각 step 종료 조건)

| Step | 진리값 | 깨지면 |
|---|---|---|
| 6 | `git grep harbor.mlplatform.local` 0개, `python -c "Compiler().compile(...)" ` 통과 | 컴포넌트 시그니처 정합성 깨진 자리. 그 자리에서 고친다. |
| 7 | `docker pull kfp-registry:5000/mlplatform/trainer:<tag>` 성공 | Dockerfile 또는 build-and-push 스크립트가 harbor 가정. |
| 8 | `kubectl -n kubeflow get cm/mlp-endpoints secret/mlp-s3` 둘 다 존재 | RBAC 확인. |
| 9 | `mc ls pi/datasets/demo/iris/` 에 csv 보임 | MinIO 자격 또는 네트워크. |
| 10 | KFP UI 의 run 이 `register_to_mlflow` 까지 초록 | 컴포넌트 내부 import 실패 → trainer image 의존성. |
| 11 | `miss=OK` 한 줄 이상 | register_to_mlflow 의 set_model_version_tag 호출 실패. |

---

## 11. Hand-off rules (메모)

- 새 의존성 추가 금지 (카파시: numpy/pandas/torch 외엔 한 줄 정당화 PR 본문에).
- `try/except` 추가 금지 (외부 API/사용자 입력 경계만).
- 한 step 끝날 때마다 **실제로 동작한 증거** (curl 출력, KFP run id, `kubectl get` 결과) 를 PR 본문에 붙일 것. "스크린샷 없으면 안 한 것."
- 막히면 README 가 진리원본 아님 — 코드와 이 문서가 진리원본. 모순 발견 시 코드를 신뢰.
