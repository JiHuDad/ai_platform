# Claude/Codex Last Diff Summary

Snapshot: 2026-05-25 KST.

## What Changed

- Fixed `ml-webhook` drift trigger flow:
  - KFP list-runs compatibility
  - latest pipeline version selection
  - idempotency after successful submit
  - ignore non-`model_drift` alerts
  - pass `BASE_DATASET_URI`
- Added NetworkPolicy for `mlops/ml-webhook` -> `kubeflow/ml-pipeline:8888`.
- Fixed KFP artifact output handling in `preprocess.py`.
- Disabled finetune task caching.
- Added serving RBAC so `kubeflow:pipeline-runner` can create promote Jobs.
- Hardened `canary-job/promote.py`:
  - stable readiness guard
  - first-stable creation from canary
  - stable logger/revision labels
  - configurable short test steps
  - canary deployment scale-to-zero
- Updated smoke/drift scripts to KServe v2 payloads.

## Verification

Passed:

```text
manual Evidently job completed with least-privilege monitoring MinIO user
Pushgateway drift metrics present: mlp_drift_score=1, feature_drift_count=4
ml-webhook /trigger submitted finetune run
finetune produced MLflow v13
mlp-canary served v13 and /v2/models/mlp/infer returned HTTP 200
manual promote job completed
MLflow aliases: production=v13, previous=v12, staging=v13
mlp-stable Ready=True with 2 pods
VirtualService weights: 100 0
canary deployment scaled to 0/0
```

Failed but fixed:

```text
trigger-promote-job 403 on jobs.batch create
v1 smoke curl failed with KeyError: inputs
manual promote with http://mlflow.mlflow:5000 DNS failure
```

## Current Caveats

- The specific KFP run `mlp-finetune-jkkrn` remains failed historically because the promote RBAC was missing at that time.
- Promotion was manually validated with `PROMOTE_STEPS=100:60`; default production dwell remains longer.
- SLO gate still needs a real traffic load test.
- Disk usage on `leaf007` is high enough to plan cleanup before more heavy cycles.

## Next

Commit current tracked changes after review, then run a fresh drift-triggered finetune to ensure the entire KFP run now ends `Succeeded` without manual promote.
