# 모델 개발 가이드

이 플랫폼은 *tabular classification* 의 *demo iris 흐름* 으로 검증됐다. 다른 모델/dataset 을 *얼마나 코드 변경* 으로 추가 가능한지의 가이드.

## 0. TL;DR

- **CSV + label 컬럼의 tabular classification** → *코드 변경 0*. dataset 업로드 + KFP run 인자 변경만.
- 다른 modality / architecture → 변경 양 따라 §3~§5.

> 검증됨 (2026-05-29): `wine` (178 rows / 13 features / 3 classes) 을 *코드 변경 0* 으로
> train→MLflow 등록→KServe serving→gateway predict 200 (`predictions=[0]`) 까지 통과.
> 단 이 검증 과정에서 train_mlp 의 torchserve `.mar` name 이 `mlp` 하드코딩이던 버그를
> 잡아 `model_name` 전달로 fix (commit 78e36c8). 그 fix 이후로 진짜 코드 변경 0.

## 1. 가장 짧은 path — Tabular classification (코드 변경 0)

### 1.1 dataset 준비

CSV 한 줄에 다음 두 종류 컬럼:

- *Feature 컬럼*: numerical 값. 컬럼 이름 자유 (`sepal_length`, `age`, `income` 등).
- *Label 컬럼* (필수): 컬럼 이름 정확히 `label`. 값은 정수 (multi-class) 또는 0/1 (binary).

예시 (`wine.csv`):

```csv
alcohol,malic_acid,ash,...,label
14.23,1.71,2.43,...,0
13.20,1.78,2.14,...,0
...
```

### 1.2 Pi4 MinIO 에 업로드

```bash
docker run --rm --network host --entrypoint sh minio/mc -c "
  mc alias set pi http://192.168.1.37:9000 admin 'ChangeMe!2026' >/dev/null
  mc cp /local/wine.csv pi/datasets/wine/$(date +%Y%m%d)-v1/wine.csv
"
```

규약: `s3://datasets/<MODEL_NAME>/<DATE>-v<N>/<file>.csv`. *MODEL_NAME* 이 이후 모든 단계의 키.

### 1.3 KFP run 제출

```bash
cd /home/fall/dev/ai_platform
source .venv/bin/activate
kubectl -n kubeflow port-forward svc/ml-pipeline 8888:8888 >/tmp/kfp-pf.log 2>&1 &
sleep 3

python scripts/submit-run.py \
  --name train-wine-v1 \
  --git-sha wine-v1 \
  --model wine \
  --dataset s3://datasets/wine/$(date +%Y%m%d)-v1/ \
  --epochs 30
```

`scripts/submit-run.py` 가 caching 을 끄고 (smoke 사고 방지) 실행. RUN_ID 가 출력됨.

### 1.4 결과 검증

```bash
# KFP UI (선택)
echo "http://localhost:8888/#/runs/details/<RUN_ID>"

# MLflow 등록 확인
python - <<'PY'
import mlflow
mlflow.set_tracking_uri("http://192.168.1.37:5001")
from mlflow.tracking import MlflowClient
c = MlflowClient()
rm = c.get_registered_model("wine")     # ← MODEL_NAME 매칭
print("aliases:", rm.aliases)
for mv in c.search_model_versions("name='wine'"):
    full = c.get_model_version(mv.name, mv.version)
    tags = full.tags if isinstance(full.tags, dict) else {t.key: t.value for t in full.tags}
    print(f"  v{mv.version}  test_accuracy={tags.get('test_accuracy','?')}  git_sha={tags.get('git_sha','?')}")
PY

# Serving 확인
kubectl -n serving get isvc wine-canary

# 첫 predict (gateway)
curl -s -H 'Host: wine.mlplatform.local' \
  -H 'Content-Type: application/json' \
  -d '{"inputs":[{"name":"input-0","shape":[1,13],"datatype":"FP32","data":[[14.23,1.71,2.43,...]]}]}' \
  http://192.168.1.154/v2/models/wine/infer
```

### 1.5 (선택) MLflow alias 옮기기

처음 학습 후 staging → production 이동:

```bash
python - <<'PY'
import mlflow
mlflow.set_tracking_uri("http://192.168.1.37:5001")
from mlflow.tracking import MlflowClient
c = MlflowClient()
c.set_registered_model_alias("wine", "production", "1")
PY
```

이후 drift 자동 finetune 이 동작하려면 *production* alias 가 있어야 (pull_production_model 이 그것 사용).

---

## 2. 자동 drift→finetune 흐름

§1 의 학습이 끝나면 *그 model 도 자동 finetune 대상* — 단 두 가지가 충족돼야:

1. **MLflow `production` alias 가 그 모델에 있어야** — finetune 의 pull_production_model 이 그것 참조.
2. **PrometheusRule `mlp-drift` 가 그 모델 라벨도 매치** — 현재는 `model="mlp"` hardcoded.

후자는 *PromQL 의 `mlp_drift_score{model="mlp"}` 가 `mlp_drift_score{model=~"mlp|wine"}` 또는 `mlp_drift_score{}` 으로 변경* 필요. 또는 *모델 별 PrometheusRule 복제*.

```yaml
# monitoring/alerts/wine-drift.yaml (mlp-drift.yaml 의 mlp → wine 으로 복제)
```

Phase 3.5 의 영역.

---

## 3. Tabular regression (반 코드 변경)

`evaluate.py` 의 accuracy metric → MSE/MAE/R²:

```python
# pipelines/components/evaluate.py 안의 본문 일부
preds = model(torch.from_numpy(X).float()).squeeze().numpy()
mse = float(((preds - y) ** 2).mean())
out = {"test_mse": mse, ...}
# passed gate: mse < baseline_mse (작을수록 좋음 — 부호 반전)
```

또 `train_mlp.py` 의 `n_classes = max(y) + 1` 계산 + CrossEntropyLoss → `nn.Linear(prev, 1) + MSELoss`.

한 chapter 의 작업.

---

## 4. 다른 architecture (CNN / Transformer)

`pipelines/components/train_mlp.py` 의 MLP class 를 새 class 로:

```python
# CNN 예시
class CNN(pl.LightningModule):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(3, 32, 3), nn.ReLU(),
            nn.Conv2d(32, 64, 3), nn.ReLU(),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(),
            nn.Linear(64, n_classes),
        )
    ...
```

단 *input shape 가정* 이 다름:
- MLP: `(B, n_features)` — preprocess 가 줌
- CNN: `(B, C, H, W)` — *preprocess 가 image 로딩* 까지 해야

→ `preprocess.py` 도 같이 손대야 (numpy npz 대신 tensor / dataloader).

**권장**: 새 component `train_cnn.py` 별도 작성 + 새 파이프라인 `pipelines/train_cnn_pipeline.py`. trainer image 는 그대로 (pytorch CPU base 가 *충분*).

---

## 5. 다른 modality (Image / NLP)

가장 큰 작업. 컴포넌트 *대부분 다시 작성*:

- `data_ingest`: csv 대신 image 디렉토리 또는 text 코퍼스
- `preprocess`: resize/tokenize → tensor
- `train_<name>`: architecture
- `handler.py`: KServe v2 OIP 의 input 형식 (image 는 base64, text 는 string)
- `register_to_mlflow`: 모델 artifact 의 *추가 파일* (vocab, tokenizer config)

trainer image 는 *base 만 같음* (`python:3.10-slim + torch`). 추가 패키지 (예: `transformers`, `torchvision`, `pillow`) 는 `requirements.txt` 에 추가.

새 image 가 *반드시 필요* 한 건 아니지만, 컴포넌트 본문이 무거우면 별도 image 권장.

---

## 6. 자주 만날 함정

- **`label` 컬럼명**: preprocess 가 정확히 `df["label"]` 사용. 다른 이름이면 깨짐.
- **MLflow `production` alias**: 첫 학습 후 자동 부여 안 됨 — `staging` 만. 수동으로 production 이동 (§1.5).
- **PrometheusRule 의 model label**: 새 모델 추가 시 drift alert 가 *그 모델* 도 매치하게 rule 복제 또는 regex.
- **KFP cache**: 같은 dataset_hash + epochs 등 input 이면 *옛 산출물 재사용*. `submit-run.py` 의 default `enable_caching=False` 가 방지.
- **InferenceService 가 안 뜨는 경우**: `kubectl -n serving describe isvc <model>-canary` 의 events 확인. 자주 만나는 자리:
  - storageUri 의 `s3://mlflow-artifacts/...` path 가 *진짜로 존재* 하는지
  - KServe storage-initializer 의 자격증명 (kserve-s3 SA + minio-s3-creds secret 의 Pi4 endpoint)
  - torchserve 의 `config.properties` + `mlp.mar` layout (train_mlp 가 자동 생성하므로 보통 OK)

---

## 7. 두 번째 모델 검증 시나리오 (예제)

sklearn 의 `load_wine` 으로 빠른 검증:

```bash
cd /home/fall/dev/ai_platform/fixtures
python - <<'PY'
import pandas as pd
from sklearn.datasets import load_wine
w = load_wine(as_frame=True)
df = w.frame.rename(columns={"target": "label"})
df.columns = [c.replace(" ", "_").replace("/", "_") for c in df.columns]
df.to_csv("wine.csv", index=False)
print(f"wrote wine.csv n={len(df)}")
PY

docker run --rm --network host --entrypoint sh -v "$PWD:/work" minio/mc -c "
  mc alias set pi http://192.168.1.37:9000 admin 'ChangeMe!2026' >/dev/null
  mc cp /work/wine.csv pi/datasets/wine/$(date +%Y%m%d)-v1/wine.csv
"

cd ..
source .venv/bin/activate
python scripts/submit-run.py --name train-wine-v1 --git-sha wine-v1 \
  --model wine --dataset s3://datasets/wine/$(date +%Y%m%d)-v1/ --epochs 30
```

위 명령으로 *코드 변경 0 으로 두 번째 모델* 검증. KFP UI 에서 run 끝나면 MLflow 에 `wine` v1 등장.

---

## 8. 한 단계 더 — production 운영

iris/wine 같은 toy 가 아닌 *진짜 모델* 운영 시 *반드시* 추가:

1. **`s3://reference-data/<model>/current/reference.parquet`** — Evidently 의 drift baseline. preprocess 가 *각 version path* 에만 업로드 → `current` alias 추가 (preprocess.py 수정 또는 별도 step).
2. **`s3://inference-logs/<model>/labeled/<run>.jsonl`** — labeled inference logs. assemble_finetune_dataset 가 이것을 base 와 합쳐 *진짜 새 dataset* 생성. 부재 시 base only → register dedup → 새 version 안 만들어짐.
3. **PrometheusRule 의 model label** 을 새 모델 포함하게.
4. **MLflow production alias** 를 첫 학습 후 수동 부여.
5. **load test** — 실제 traffic 하에 SLO gate 검증.

이 5 가지가 *진짜 production 운영* 의 입구.

---

## 9. 빠른 명령 참조

```bash
# 환경 wake-up
source .venv/bin/activate
kubectl -n kubeflow port-forward svc/ml-pipeline 8888:8888 >/tmp/kfp-pf.log 2>&1 &

# dataset 업로드
docker run --rm --network host --entrypoint sh -v "$PWD:/work" minio/mc -c "
  mc alias set pi http://192.168.1.37:9000 admin 'ChangeMe!2026' >/dev/null
  mc cp /work/<file>.csv pi/datasets/<MODEL>/$(date +%Y%m%d)-v1/
"

# train
python scripts/submit-run.py --name train-<MODEL>-v1 --git-sha v1 \
  --model <MODEL> --dataset s3://datasets/<MODEL>/$(date +%Y%m%d)-v1/

# alias 이동 (staging → production)
python -c "
from mlflow.tracking import MlflowClient; import mlflow
mlflow.set_tracking_uri('http://192.168.1.37:5001')
MlflowClient().set_registered_model_alias('<MODEL>', 'production', '<N>')
"

# predict (Istio gateway)
curl -s -H 'Host: <MODEL>.mlplatform.local' \
  -H 'Content-Type: application/json' \
  -d '{"inputs":[{"name":"input-0","shape":[1,<F>],"datatype":"FP32","data":[[...]]}]}' \
  http://192.168.1.154/v2/models/<MODEL>/infer
```
