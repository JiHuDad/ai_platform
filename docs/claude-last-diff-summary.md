# Claude/Codex Last Diff Summary

Snapshot: 2026-05-25 KST.

## What Changed

- Added `serving/inference-logger/` FastAPI app and image.
- Added `inference-logger` to `images/build-and-push.sh`.
- Updated `serving/inference-logger.yaml` to use Pi4 MinIO.
- Updated `monitoring/evidently-job/run.py`:
  - fallback from missing `current` reference to latest available reference
  - parse logger/KServe v2 payload shapes
- Updated `monitoring/evidently-job/cronjob.yaml`:
  - Pi4 MinIO endpoint
  - removed embedded MinIO credentials

## Verification

Passed:

```text
python3 -m py_compile monitoring/evidently-job/run.py serving/inference-logger/main.py
docker build/push:
  mlplatform/evidently-job:ph3-logger, latest
  mlplatform/inference-logger:ph3-logger, latest
kubectl rollout status deploy/inference-logger -n serving
KServe gateway inference HTTP 200
inference-logger POST /log/mlp/canary HTTP 200
MinIO inference-logs objects created
```

Failed/blocked:

```text
manual evidently job -> InvalidAccessKeyId
```

Reason: `monitoring-minio-creds` currently contains credentials rejected by Pi4 MinIO.

## Next

Ask the user to approve creating a least-privilege MinIO user for monitoring. Then update only the Kubernetes Secret, rerun `evidently-mlp-manual`, and verify Pushgateway metrics.

