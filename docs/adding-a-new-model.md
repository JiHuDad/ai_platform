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
