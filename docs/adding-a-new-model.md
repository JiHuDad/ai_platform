# 새 모델 추가하기

이 저장소에 새 모델을 추가하려고 들어온 사람을 위한 가이드. 두 시나리오를 다룬다:

- **시나리오 A**: 같은 MLP 아키텍처, **새 task/dataset** — 30분, 파라미터 + 데이터셋만 바꿈
- **시나리오 B**: **새 아키텍처** (ResNet, Transformer 등) — 반나절, 새 학습 컴포넌트 + handler 작성

CLAUDE.md 원칙대로 — 추상화하지 말고 *복사 → 이름만 바꿔라*. 두 번째 모델이 추가된 다음에야 공통화를 고민한다.

검증의 단일 진리원본은 `scripts/e2e_smoke.sh`. 깨지면 머지 금지.

---

## TL;DR — 어디부터 손대야 하는지

| 영역 | 시나리오 A | 시나리오 B |
|------|:-----------:|:-----------:|
| 데이터셋 업로드 (`s3://datasets/...`) | ✅ | ✅ |
| 파이프라인 호출 시 `model_name` 변경 | ✅ | (불필요 — 새 파이프라인) |
| 새 학습 컴포넌트 `pipelines/components/train_{arch}.py` | — | ✅ |
| 새 파이프라인 `pipelines/{train,finetune}_{arch}_pipeline.py` | — | ✅ |
| `pipelines/compile-and-register.sh` 에 upload 2줄 추가 | — | ✅ |
| TorchServe handler (`images/trainer/handler.py`) | — | ✅ (generic 하지 않다면) |
| 이미지 재빌드 (`images/build-and-push.sh`) | — | ✅ |
| Webhook 환경변수 (`controller/webhook/deploy.yaml`) | — | ✅ |
| Drift 알림 룰 (`monitoring/alerts/`) | — | ✅ |
| Evidently CronJob (`monitoring/evidently-job/`) | — | ✅ |
| `e2e_smoke.sh` 통과 | ✅ | ✅ |

서빙 템플릿 `serving/inferenceservice/mlp.yaml.j2` 는 이미 `{{ base_name }}` 로 generic — 새 파일 불필요.

---

## 누가 무엇을 책임지나 — 책임 경계

이 플랫폼은 **모델 dev** 와 **플랫폼 팀** 두 역할로 나뉜다. 단일 목표:
**모델 dev 가 KFP/MLflow/KServe 라는 단어를 한 번도 안 보는 것**.

| 누가 | 무엇을 | 언제 |
|------|--------|------|
| 플랫폼 팀 | `pipelines/components/train_external.py` (모든 외부 모델용 *접수창구*) | 처음 1회 — **현재 TBD** |
| 플랫폼 팀 | drift 룰 + Evidently CronJob + ConfigMap 키 (5분 복사) | 매 모델 |
| 플랫폼 팀 | 새로운 *결* (RL, multi-modal 등) 처음 들어올 때 `train_external_<결>.py` | 새 결마다 1회 |
| 모델 dev | `model.py`, `data.py`, `model.yaml`, `requirements.txt` (자기 repo) | 매 모델 |
| 모델 dev | 데이터셋 업로드 (`s3://datasets/{name}/v1/`) | 매 모델 |
| 자동 | KServe InferenceService, Istio VS, MLflow 등록, lineage 5종 부착 | — |

**원칙**: 현재 시나리오 A/B 는 *과도기*. `train_external.py` 가 만들어진 다음부터는
시나리오 C (아래) 가 디폴트. CLAUDE.md 의 *증명된 중복 다음에만 추상화* 룰에 부합한다.

---

## Lineage 5종 (절대 빠뜨리지 말 것)

모든 MLflow 모델 버전은 다음 5종 태그를 가져야 한다:

```
dataset_uri      # s3:// 학습 데이터셋 경로
dataset_hash     # SHA256 (재현성)
git_sha          # ML 코드 commit SHA
kfp_run_id       # KFP run ID (재현성)
triggered_by     # "manual" | "drift" | "scheduled"
```

→ `pipelines/components/register_to_mlflow.py:56-67` 가 자동 부착한다. **파이프라인 호출 시 이 값들을 전달만 잘 하면 OK**. fine-tune 인 경우 `base_dataset_uri` 추가.

검증: `./scripts/e2e_smoke.sh 9` — 모든 버전이 5종을 가지고 있는지 출력. `miss=none` 이어야 함.

---

## 시나리오 A — 같은 MLP, 새 task/dataset

예: tabular 데이터셋 추가 (iris2, titanic 등). 같은 `train_mlp` 컴포넌트 + 같은 파이프라인 재사용.

### 체크리스트

- [ ] **데이터셋 업로드**: `s3://datasets/{domain}/{name}/v1/` 에 CSV/Parquet 적재
      `kubectl -n minio exec -i deploy/minio -- mc cp` 또는 `fixtures/make-iris.py` 패턴 참고
- [ ] **`train_mlp.py:127, 136, 154` 의 하드코딩 수정** — `--model-name mlp`, `"mlp"` 키, `load_models=mlp.mar` 가 동적이어야 함. 두 번째 모델 추가 시 한 번만 손보면 됨. PR 같이 묶을 것
- [ ] **파이프라인 호출**: `scripts/submit-run.py` 또는 KFP UI 에서 `model_name=<new>`, `dataset_uri=<s3 path>` 로 `mlp-train` 파이프라인 실행
- [ ] **(필요시) 하이퍼파라미터 조정**: `hidden_dims`, `lr`, `epochs` — 데이터 크기/feature 수에 맞춰
- [ ] **MLflow 확인**: 새 `{model_name}` 등록 모델이 만들어지고 `staging` alias 가 붙는지
- [ ] **추론 호출**: `curl /v2/models/{model_name}/infer` → HTTP 200 + 예측 body
- [ ] **`MODEL={model_name} ./scripts/e2e_smoke.sh all`** 통과

### 주의

`scripts/e2e_smoke.sh:131` 의 step 9 가 `name='mlp'` 로 하드코딩 — 다른 모델명으로 돌릴 거면 같이 고치거나, step 9 만 `mlp` 로 따로 검증.

`step 6` 의 `pipeline/name=mlp-finetune` 도 마찬가지.

---

## 시나리오 B — 새 아키텍처

예: ResNet, Transformer 등 새 모델 아키텍처. 새 KFP 컴포넌트 + handler + 파이프라인 필요.

### 체크리스트

#### 학습 코드

- [ ] **새 학습 컴포넌트** `pipelines/components/train_{arch}.py`
      - `pipelines/components/train_mlp.py` 를 reference. 80줄 내외 유지. `nn.Sequential` 한 줄로 표현 가능하면 그렇게
      - 입출력 시그니처는 동일하게 유지:
        ```
        train_npz, val_npz, ..., model_out, metrics_out
        ```
      - `model_out` 디렉토리 구조도 동일:
        ```
        state_dict.pt
        model.pt              # TorchScript
        meta.json
        model-store/{arch}.mar
        config/config.properties
        ```
      - `torch-model-archiver --model-name {arch}` / `load_models={arch}.mar` 가 정확해야 KServe wrapper 가 모델을 찾는다 (`train_mlp.py:127-156` 참고)

- [ ] **TorchServe handler** — 기본 `images/trainer/handler.py` 가 새 모델의 입출력 텐서 shape 을 처리할 수 있는지 확인
      - 안 되면 `images/trainer/handler_{arch}.py` 추가 + `Dockerfile:29` 의 COPY 라인 옆에 한 줄 추가
      - 그리고 위의 archiver 호출에서 `--handler /templates/handler_{arch}.py`

#### 파이프라인

- [ ] **`pipelines/train_{arch}_pipeline.py`**
      - `pipelines/train_pipeline.py:1-77` 복사 → `train_mlp` import 만 `train_{arch}` 로 교체
      - `@dsl.pipeline(name="{arch}-train", ...)`

- [ ] **`pipelines/finetune_{arch}_pipeline.py`**
      - `pipelines/finetune_pipeline.py` 복사 → 같은 식으로 import 교체
      - `@dsl.pipeline(name="{arch}-finetune", ...)`

- [ ] **`pipelines/compile-and-register.sh:18-50` 수정**
      - import 2줄 + `upload("{arch}-train", ...)` + `upload("{arch}-finetune", ...)` 2줄
      - ConfigMap `pipeline-ids` 에 키 `{arch}-train`, `{arch}-finetune` 추가 (`compile-and-register.sh:64-67`)

#### 이미지

- [ ] **`images/build-and-push.sh`** 실행 — handler 또는 추가 의존성이 들어갔으면 trainer 이미지 재빌드
      - 새 의존성은 PR 본문에 한 줄 정당화 (CLAUDE.md 규칙)

#### 배포 / 서빙

- [ ] **서빙 템플릿은 그대로** — `serving/inferenceservice/mlp.yaml.j2` 가 `{{ base_name }}` 로 generic. 새 j2 파일 만들지 말 것
- [ ] **Istio VirtualService 도 그대로** — `deploy_canary.py` 가 모델명으로 자동 생성

#### Webhook 자동화

- [ ] **`controller/webhook/deploy.yaml`** 환경변수에 `{ARCH}_FINETUNE_PIPELINE_ID` 추가 (또는 ConfigMap reference)
- [ ] **`controller/webhook/main.py`** — alert label `model={arch}` 가 들어왔을 때 올바른 pipeline_id 를 선택하는지 확인
      - 현재는 `pipeline-ids` ConfigMap 의 `finetune` 키 하나만 본다 → 모델별 분기 필요

#### 모니터링

- [ ] **`monitoring/alerts/mlp-drift.yaml`** 복사 → `{arch}-drift.yaml`
      - PrometheusRule 의 `expr` 에서 `model="{arch}"` 라벨로 변경
      - Alertmanager 가 webhook 으로 `model` label 을 그대로 forward 하는지 확인

- [ ] **`monitoring/evidently-job/cronjob.yaml`** — 새 모델용 reference 분포 경로 (`s3://reference-data/{arch}/...`) 와 inference-logs 경로 (`s3://inference-logs/{arch}/...`) 추가

#### 데이터 / 검증

- [ ] **데이터셋 업로드**: `s3://datasets/{domain}/{name}/v1/`
- [ ] **첫 promote 는 짧은 dwell**: `PROMOTE_STEPS=100:60` 로 dry-run (`controller/canary-job/promote.py` 참고)
- [ ] **`MODEL={arch} ./scripts/e2e_smoke.sh all`** 통과

---

## 시나리오 C — Contract-based (권장 상태, 현재 TBD)

> **상태**: 미구현. `train_external.py` 가 만들어지면 활성화.
> 두 번째 외부 모델이 들어오는 시점에 시나리오 A/B 대신 이 경로 사용.

목표: **모델 dev 는 자기 repo 만 만지고, 플랫폼 코드는 안 본다.**

### 모델 repo 가 제공해야 하는 것 (contract)

```python
# model.py
def make_model(config: dict) -> torch.nn.Module: ...
def loss_fn(logits, targets) -> torch.Tensor: ...

# data.py — uri 받아서 train/val/test 반환
def load_dataset(uri: str) -> tuple[Dataset, Dataset, Dataset]: ...
def reference_distribution(train) -> dict: ...   # drift 기준
```

```yaml
# model.yaml — 한 페이지로 끝나는 선언
name: tractor
image: pytorch/pytorch:2.3.0-cpu        # base image (extras 는 requirements.txt)
dataset_uri: s3://datasets/tractor/v1/
hyperparameters: {lr: 1e-3, epochs: 20, batch_size: 256}
serving: {handler: generic_tabular, protocol: v2}
monitoring: {drift_metric: psi, threshold: 0.2}
```

### 모델 dev 체크리스트 (이것만)

- [ ] 새 repo 생성 — 위 4개 파일 (`model.py`, `data.py`, `model.yaml`, `requirements.txt`)
- [ ] `model.py` / `data.py` 가 contract 시그니처 충족
- [ ] 데이터셋을 `s3://datasets/{name}/v1/` 에 업로드
- [ ] 플랫폼 팀에 PR 요청 — "내 repo URL 등록 부탁드림"

### 플랫폼 팀 체크리스트 (5분, 향후 자동화)

- [ ] `compile-and-register.sh` 에 한 줄 — `model.yaml` URL 추가
- [ ] 자동 생성 스크립트 (아래 *N개 모델 운영* 섹션) 실행 → drift/evidently 파일 생성
- [ ] commit + push

### 동작 원리

`train_external.py` (KFP 컴포넌트) 가 런타임에:

1. `pip install <model_repo>` 또는 git clone
2. `model.yaml` 파싱 → 환경변수로 주입
3. `model.make_model(config)`, `data.load_dataset(uri)` 호출
4. 학습, 저장, lineage 5종 부착 (기존 `register_to_mlflow.py` 재사용)
5. 이후 (deploy_canary, promote, rollback) 는 모두 기존 컴포넌트 그대로

→ 플랫폼은 *한 번* `train_external.py` 만 추가. 나머지는 contract 가 흡수.

### 한계 (정직하게)

- **새 modality** (RL, multi-modal, signal processing 등) 는 기존 contract 가 못 표현 → 플랫폼 팀이 `train_external_<결>.py` 를 *한 번 더* 작성
- **Serving 입출력 텐서 형태** — KServe 가 모르는 형식이면 모델 repo 에 `handler.py` 한 장은 들어감. 완전한 0-touch 불가

---

## 검증 (둘 다 동일)

```bash
# 핵심 — 9단계 전부 GREEN
MODEL={model_name} ./scripts/e2e_smoke.sh all

# 개별 단계만 돌리기
MODEL={model_name} ./scripts/e2e_smoke.sh 2   # 학습 파이프라인
MODEL={model_name} ./scripts/e2e_smoke.sh 9   # lineage 5종 확인
```

수동 확인:
- MLflow UI: 새 모델 등록 + `staging`/`production` alias 정상
- Grafana 대시보드: drift score, latency, error rate 메트릭 emit
- KServe: `kubectl -n serving get isvc` 에 `{model_name}-stable`, `{model_name}-canary` Ready

---

## 롤백 (실수했을 때)

```bash
# 1. 빠른 롤백 — canary 트래픽 차단
kubectl -n serving patch vs {model_name} --type=merge \
  -p '{"spec":{"http":[{"route":[{"weight":100},{"weight":0}]}]}}'

# 2. MLflow alias 정리
mlflow models registry transition_stage ...   # 또는 alias 수동 이동

# 3. 깊은 롤백 — 직전 manifest 스냅샷에서 복구
mc cp dst/serving-manifests/{model_name}/{ts}/stable-isvc.yaml - | kubectl apply -f -
```

자세한 동작 / 자동화는 `controller/rollback-job/rollback.py`. Alertmanager 가 `severity=critical` alert 을 보내면 자동으로 동일한 절차를 밟는다.

---

## N개 모델 운영 시 — 자동 생성 스크립트

두 번째 모델까지는 *손 복사* 가 정직하다 (CLAUDE.md: *증명된 중복 다음에 추상화*).
세 번째 모델이 들어오기 직전에 — 같은 복사가 3번 반복되기 전 — `model.yaml` 을 읽어
boilerplate 를 *자동 생성* 하는 스크립트를 만든다.

### 자동 생성 대상

| 파일 | 매번 다른 것 |
|------|------------|
| `monitoring/alerts/{model}-drift.yaml` | `model` label, threshold |
| `monitoring/evidently-job/{model}-cronjob.yaml` | reference / inference 경로 |
| `compile-and-register.sh` 의 upload 줄 | 파이프라인 이름 |
| ConfigMap `pipeline-ids` 키 | `{name}-train`, `{name}-finetune` |

### 제안 도구

`scripts/render_per_model_config.py` (TBD):

```bash
# 모든 model.yaml 을 훑고 위 4종을 재생성 — idempotent.
python scripts/render_per_model_config.py models/*.yaml
```

### 만들 시점

| 모델 수 | 권장 |
|:-------:|------|
| 1~2개 | 손 복사 (10분/모델) |
| 3개째 | 위 스크립트 작성 (1시간), 기존 2개도 재생성 |
| 5개 이상 | 스크립트를 CI 에 넣어 PR 시 자동 verify |

---

## 자주 빠뜨리는 것

- **`git_sha`** — 파이프라인 호출 시 환경변수 안 넘기면 lineage 가 `"unknown"`. CI 또는 submit 스크립트에서 `git rev-parse HEAD` 로 전달
- **`load_models=mlp.mar`** — 새 모델명으로 안 바꾸면 KServe 가 모델을 못 찾는다 (`train_mlp.py:154`)
- **Reference 분포 경로** — `preprocess` 가 `s3://reference-data/{model_name}/{version}/` 에 저장. Evidently CronJob 도 같은 경로를 봐야 drift 계산 가능
- **`baseline_accuracy=0`** — finetune 첫 회는 0 으로 두지 말 것. 현 production accuracy 를 넘겨야 evaluate gate 가 의미 있음 (`pipelines/finetune_pipeline.py` 의 `pull_production_model` 출력 사용)
- **dataset_hash 중복** — `register_to_mlflow.py:40-45` 가 `dataset_hash + git_sha` 같으면 새 버전 안 만든다. 의도된 동작 (재현성). 진짜 retrain 하려면 데이터셋 또는 코드 변경 필요

---

## 새 모델 추가 후 — 한 줄 PR 본문 예시

> `{arch}` 학습/배포 파이프라인 추가. e2e_smoke.sh (`MODEL={arch}`) 9단계 통과,
> MLflow lineage 5종 OK, canary 10→100% 정상 step-up. KFP run: `<id>`.

Karpathy 규칙: *prose later, evidence first*. run id, metric 캡쳐, e2e 통과 로그.
