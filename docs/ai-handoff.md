# AI Handoff — ai_platform

Snapshot: 2026-05-25 (KST late afternoon — Phase 2.5 종료, Phase 3 진입 자격 충족)

This handoff is for a fresh coding agent. Read this file, `docs/claude-last-diff-summary.md`, `AGENTS.md`, `CLAUDE.md`, and `git diff` before editing.

## Objective

**Phase 2.5 ✅ DONE.** mlp v12 가 진짜 inference HTTP 200 응답 (internal + gateway 둘 다, predictions=[2]). Phase 3 (drift→finetune→canary→promote/rollback 자동화 루프) 진입 자격 충족.

## Phase 2.5 의 진짜 진실 (사용자 직접 검증)

```text
mlp-canary READY=True
revision=mlp-v12
MLflow staging alias = 12
VirtualService stable=0 canary=100
handler.py in predictor = 2918 bytes (새 v2 handler)

internal: POST 127.0.0.1:8080/v2/models/mlp/infer → 200, predictions=[2]
gateway:  POST http://192.168.1.154/v2/models/mlp/infer Host=mlp.mlplatform.local → 200, predictions=[2]
```

## 진짜 원인 (회고)

B1 archive 의 옛 handler 자리 = **KFP step cache** 였음. train_mlp 가 dataset_hash + epochs 등 input 동일하면 *옛 산출물 재사용*. handler.py 변경은 *컴포넌트 함수 본문* 안에 반영되지만 KFP cache 는 *function body hash + input hash* 로 cache key. handler.py 가 본문 안 import 가 아니라 *image 의 외부 파일* 이라 KFP cache 가 변경 감지 못 함.

→ Smoke 용 run 은 `enable_caching=False` 가 default. `scripts/submit-run.py --cache` 로만 cache 활성. commit `???` 참조.

## Current State

Repository: `/home/fall/dev/ai_platform` on `fall@192.168.1.154`.

Git:

```bash
git status --short --branch
```

Current result:

```text
## main...origin/main [ahead 1]
 M serving/inferenceservice/mlp.yaml.j2
?? AGENTS.md
```

Latest commit:

```text
df455a7 feat: TorchServe config.properties 정합 — predictor pod 진짜 Ready
```

`origin/main` is still at:

```text
205f55a docs: phase 2.5 image 준비 — run-8 검증을 다음 세션 첫 작업으로
```

Cluster:

```text
leaf007 Ready, k3s v1.29.14+k3s1
serving/mlp-canary InferenceService READY=True
serving/mlp-canary pods: 2/2 Running x2
```

Current KServe truth:

```text
isvc=mlp-canary
ready=True
revision=mlp-v10
storage=s3://mlflow-artifacts/0/b2f4e2e3f7e942cda5cc5c2424fe9b1d/artifacts/model
protocol=v2
```

Current MLflow truth:

```text
registered model: mlp
aliases: {'staging': '10'}
v9  run=b996dd6dfe794847a345efeeeab629d2  test_accuracy=0.782608695652174  git_sha=p2.5-ports
v10 run=b2f4e2e3f7e942cda5cc5c2424fe9b1d  test_accuracy=0.782608695652174  git_sha=p2.5-v2protocol
dataset_uri=s3://datasets/demo/iris/20260523-v1/
dataset_hash=39706f147590c33e41c0a38a1defc91020d1bca81ca67f3c375fc04e0d0554cf
```

Pi4 state (`fall@192.168.1.37`):

```text
minio    Up 12 days   0.0.0.0:9000-9001->9000-9001
registry Up 12 days   0.0.0.0:5000->5000
mlflow   Up 39 hours  0.0.0.0:5001->5000
```

## Files Changed

Committed in `df455a7`:

- `pipelines/components/train_mlp.py`
  - Builds TorchServe layout under the MLflow model artifact:
    - `model-store/mlp.mar`
    - `config/config.properties`
  - Moves TorchServe internal REST ports to `7080/7081/7082`.
  - Keeps KServe wrapper free to bind `8080/8081`.
  - Adds `model_snapshot`, `load_models=mlp.mar`, gRPC ports, metrics config.
- `scripts/submit-run.py`
  - Repeatable KFP run submitter.
  - Defaults to Iris demo data and `mlp`.

Uncommitted at handoff:

- `serving/inferenceservice/mlp.yaml.j2`
  - Adds:
    ```yaml
    protocolVersion: {{ protocol_version | default('v2') }}
    ```
  - This is required for the current `mlp-v10` serving shape.
- `AGENTS.md`
  - Tells Codex to read `CLAUDE.md`.
  - Allows optional `local-llama-sidekick` use for small advisory checks only.
- `docs/ai-handoff.md`
- `docs/claude-last-diff-summary.md`

## Decisions

- Keep using the demo `mlp` + Iris dataset until the full platform loop is green. This is not a production model choice; it is the fast sanity fixture.
- Use KServe `protocolVersion: v2` for TorchServe runtime compatibility.
- Run TorchServe on `7080/7081/7082`, not `8080/8081`, because the KServe wrapper owns the wrapper server ports.
- Keep `.mar` packaging in `train_mlp.py` for now. It is simple and matches the current "one dumb thing that works" style.
- Use `scripts/submit-run.py` instead of ad hoc heredoc KFP submissions.
- Do not start Phase 3 until `curl`/internal predict returns HTTP 200 with a prediction body.

## Current Bugs

### B1. Handler does not parse KServe v2/OIP input

The model loads and metadata works, but inference fails.

Working:

```bash
kubectl -n serving exec deploy/mlp-canary-predictor -c kserve-container -- \
  python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8080/v2/models/mlp", timeout=10); print(r.status); print(r.read().decode())'
```

Observed:

```text
200
{"name":"mlp","versions":null,"platform":"","inputs":[],"outputs":[]}
```

Failing:

```bash
kubectl -n serving exec deploy/mlp-canary-predictor -c kserve-container -- \
  python -c 'import json,urllib.request; payload=json.dumps({"inputs":[{"name":"input-0","shape":[1,4],"datatype":"FP32","data":[[5.1,3.5,1.4,0.2]]}]}).encode(); req=urllib.request.Request("http://127.0.0.1:8080/v2/models/mlp/infer", data=payload, headers={"Content-Type":"application/json"}); r=urllib.request.urlopen(req, timeout=10); print(r.status); print(r.read().decode())'
```

Observed:

```text
HTTP Error 500: Internal Server Error
```

Important log:

```text
File "/home/model-server/tmp/models/.../handler.py", line 25, in preprocess
  instances = body.get("instances") or body.get("inputs") or body
AttributeError: 'list' object has no attribute 'get'
```

Likely fix: update `images/trainer/handler.py` so `preprocess()` accepts:

- KServe v1: `{"instances": [[...]]}`
- KServe v2/OIP: `{"inputs": [{"name": "...", "shape": [N, D], "datatype": "FP32", "data": [...]}]}`
- TorchServe envelopes where the body may already be a `list`

### B2. VirtualService routes 90% to a missing stable service

Current `serving/istio/virtualservice.yaml.j2` renders both routes:

```text
mlp-stable-predictor.serving.svc.cluster.local weight=90
mlp-canary-predictor.serving.svc.cluster.local weight=10
```

But there is no `mlp-stable-predictor` service in `serving`.

Failing command:

```bash
curl -s -i \
  -H 'Host: mlp.mlplatform.local' \
  -H 'Content-Type: application/json' \
  -d '{"inputs":[{"name":"input-0","shape":[1,4],"datatype":"FP32","data":[[5.1,3.5,1.4,0.2]]}]}' \
  http://192.168.1.154/v2/models/mlp/infer
```

Observed:

```text
HTTP/1.1 503 Service Unavailable
```

Likely fix: in `pipelines/components/deploy_canary.py`, when no stable service exists, render `stable_weight=0`, `canary_weight=100`, or render only the canary route. The code already detects no stable later while snapshotting; do the stable existence check before rendering the VirtualService.

### B3. `inference-logger` is referenced but not deployed

`InferenceService` includes:

```yaml
logger:
  mode: all
  url: http://inference-logger.serving.svc/log/mlp/canary
```

But:

```bash
kubectl -n serving get svc inference-logger
kubectl -n serving get deploy inference-logger
```

Both return `NotFound`.

This has not blocked readiness, but after prediction works it may surface as logging noise or failed async delivery. Either deploy `serving/inference-logger.yaml` as part of Phase 3 or remove/guard the logger block until that component exists.

## Failing Commands

Gateway v1 request:

```bash
curl -s -i \
  -H 'Host: mlp.mlplatform.local' \
  -H 'Content-Type: application/json' \
  -d '{"instances":[[5.1,3.5,1.4,0.2]]}' \
  http://192.168.1.154/v1/models/mlp:predict
```

Observed:

```text
HTTP/1.1 503 Service Unavailable
```

Gateway v2 request:

```bash
curl -s -i \
  -H 'Host: mlp.mlplatform.local' \
  -H 'Content-Type: application/json' \
  -d '{"inputs":[{"name":"input-0","shape":[1,4],"datatype":"FP32","data":[[5.1,3.5,1.4,0.2]]}]}' \
  http://192.168.1.154/v2/models/mlp/infer
```

Observed:

```text
HTTP/1.1 503 Service Unavailable
```

Direct wrapper v2 request:

```bash
kubectl -n serving exec deploy/mlp-canary-predictor -c kserve-container -- \
  python -c 'import json,urllib.request; payload=json.dumps({"inputs":[{"name":"input-0","shape":[1,4],"datatype":"FP32","data":[[5.1,3.5,1.4,0.2]]}]}).encode(); req=urllib.request.Request("http://127.0.0.1:8080/v2/models/mlp/infer", data=payload, headers={"Content-Type":"application/json"}); r=urllib.request.urlopen(req, timeout=10); print(r.status); print(r.read().decode())'
```

Observed:

```text
HTTP Error 500: Internal Server Error
```

## Exact Next Steps

1. Start cleanly:

   ```bash
   cd /home/fall/dev/ai_platform
   git status --short --branch
   git diff
   ```

2. Fix `images/trainer/handler.py`.

   Minimum behavior:

   - Decode `bytes`/`str` JSON.
   - If body is already a list, treat it as rows.
   - If dict has `instances`, use that.
   - If dict has `inputs`, take the first input object and use its `data`; respect `shape` if `data` is flat.
   - Return `torch.tensor(rows, dtype=torch.float32)`.

3. Fix first-deploy routing in `pipelines/components/deploy_canary.py`.

   Before rendering the VirtualService:

   ```bash
   kubectl -n serving get svc mlp-stable-predictor
   ```

   If stable is absent, deploy canary at 100 and stable at 0. Do not send traffic to a nonexistent service.

4. Keep/commit the `protocolVersion: v2` template change in `serving/inferenceservice/mlp.yaml.j2`.

5. Rebuild and push trainer image from repo root:

   ```bash
   docker build -f images/trainer/Dockerfile \
     -t kfp-registry:5000/mlplatform/trainer:p2.5-v2handler \
     -t kfp-registry:5000/mlplatform/trainer:latest \
     .
   docker push kfp-registry:5000/mlplatform/trainer:p2.5-v2handler
   docker push kfp-registry:5000/mlplatform/trainer:latest
   ```

6. Make sure KFP API is reachable:

   ```bash
   kubectl -n kubeflow port-forward svc/ml-pipeline 8888:8888 >/tmp/kfp-pf.log 2>&1 &
   sleep 3
   curl -s http://localhost:8888/apis/v2beta1/pipelines | head -c 200
   ```

7. Recompile/register pipelines:

   ```bash
   pipelines/compile-and-register.sh
   ```

8. Submit the next smoke run:

   ```bash
   .venv/bin/python scripts/submit-run.py \
     --name train-smoke-11-v2handler \
     --git-sha p2.5-v2handler
   ```

9. Watch it:

   ```bash
   kubectl -n serving get isvc,vs,pods
   kubectl -n serving logs deploy/mlp-canary-predictor -c kserve-container --tail=160
   ```

10. Validate direct predictor first:

    ```bash
    kubectl -n serving exec deploy/mlp-canary-predictor -c kserve-container -- \
      python -c 'import json,urllib.request; payload=json.dumps({"inputs":[{"name":"input-0","shape":[1,4],"datatype":"FP32","data":[[5.1,3.5,1.4,0.2]]}]}).encode(); req=urllib.request.Request("http://127.0.0.1:8080/v2/models/mlp/infer", data=payload, headers={"Content-Type":"application/json"}); r=urllib.request.urlopen(req, timeout=10); print(r.status); print(r.read().decode())'
    ```

11. Validate gateway after VirtualService no longer routes to missing stable:

    ```bash
    curl -s -i \
      -H 'Host: mlp.mlplatform.local' \
      -H 'Content-Type: application/json' \
      -d '{"inputs":[{"name":"input-0","shape":[1,4],"datatype":"FP32","data":[[5.1,3.5,1.4,0.2]]}]}' \
      http://192.168.1.154/v2/models/mlp/infer
    ```

12. Only after HTTP 200 with prediction body, mark Phase 2.5 green and proceed to Phase 3:

    - deploy/verify `inference-logger`
    - build `evidently-job`, `ml-webhook`, `canary-job`, `rollback-job`
    - wire drift -> finetune -> canary -> promote/rollback

