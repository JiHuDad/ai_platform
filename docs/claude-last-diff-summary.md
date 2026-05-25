# Claude/Codex Last Diff Summary

Snapshot: 2026-05-25 12:03:20 KST

This file summarizes the live diff and the current verification result. The full handoff is in `docs/ai-handoff.md`.

## Current Diff

Branch:

```text
main...origin/main [ahead 1]
```

Committed but not pushed:

```text
df455a7 feat: TorchServe config.properties 정합 — predictor pod 진짜 Ready
```

Committed file changes in `df455a7`:

- `pipelines/components/train_mlp.py`
  - Added TorchServe `.mar` packaging.
  - Added `/mnt/models/config/config.properties`.
  - Moved TorchServe internal HTTP ports to `7080/7081/7082`.
  - Added `model_snapshot`, gRPC ports, metrics config, `load_models=mlp.mar`.
- `scripts/submit-run.py`
  - Added repeatable KFP run submission helper.

Uncommitted:

- `serving/inferenceservice/mlp.yaml.j2`
  - Adds `protocolVersion: {{ protocol_version | default('v2') }}`.
- `AGENTS.md`
  - Codex entry instructions and local llama sidekick guardrails.
- `docs/ai-handoff.md`
- `docs/claude-last-diff-summary.md`

No code fix was applied in this handoff pass beyond documenting the state.

## Verification Performed

KServe:

```text
mlp-canary READY=True
revision=mlp-v10
protocol=v2
storage=s3://mlflow-artifacts/0/b2f4e2e3f7e942cda5cc5c2424fe9b1d/artifacts/model
pods=2/2 Running x2
```

MLflow:

```text
aliases {'staging': '10'}
v9  test_accuracy=0.782608695652174  git_sha=p2.5-ports
v10 test_accuracy=0.782608695652174  git_sha=p2.5-v2protocol
dataset_uri=s3://datasets/demo/iris/20260523-v1/
```

Pi4:

```text
minio, registry, mlflow all Up
```

Direct metadata check:

```bash
kubectl -n serving exec deploy/mlp-canary-predictor -c kserve-container -- \
  python -c 'import urllib.request; r=urllib.request.urlopen("http://127.0.0.1:8080/v2/models/mlp", timeout=10); print(r.status); print(r.read().decode())'
```

Result:

```text
200
{"name":"mlp","versions":null,"platform":"","inputs":[],"outputs":[]}
```

## Current Failures

1. Direct v2 inference fails inside the predictor.

   Log:

   ```text
   File "/home/model-server/tmp/models/.../handler.py", line 25, in preprocess
     instances = body.get("instances") or body.get("inputs") or body
   AttributeError: 'list' object has no attribute 'get'
   ```

   Meaning: `images/trainer/handler.py` does not handle the actual TorchServe/KServe v2 envelope shape.

2. Gateway calls return 503 because the VirtualService sends 90% traffic to missing stable.

   Current route:

   ```text
   mlp-stable-predictor.serving.svc.cluster.local weight=90
   mlp-canary-predictor.serving.svc.cluster.local weight=10
   ```

   But only `mlp-canary-predictor` exists.

3. `inference-logger` is referenced by the InferenceService but not deployed.

   ```text
   services "inference-logger" not found
   deployments.apps "inference-logger" not found
   ```

## Next Patch

Patch these first:

- `images/trainer/handler.py`
  - parse KServe v2/OIP `inputs[0].data`
  - tolerate body already being a list
- `pipelines/components/deploy_canary.py`
  - if no stable predictor service exists, render canary 100 / stable 0 or omit stable route
- keep `serving/inferenceservice/mlp.yaml.j2` `protocolVersion: v2`

Then rebuild trainer, submit `train-smoke-11-v2handler`, and require HTTP 200 from `/v2/models/mlp/infer` before Phase 3.

