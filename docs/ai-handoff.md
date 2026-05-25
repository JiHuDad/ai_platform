# AI Handoff — ai_platform

Snapshot: 2026-05-25 KST — Phase 3 logger/Evidently wiring pass.

Read `CLAUDE.md`, `AGENTS.md`, this file, `docs/claude-last-diff-summary.md`, and `git diff` before editing.

## Objective

Continue Phase 3 E2E drift loop:

```text
KServe request -> inference-logger -> MinIO inference-logs
-> Evidently -> Pushgateway/Prometheus -> Alertmanager
-> ml-webhook /trigger -> finetune_pipeline -> canary -> promote
```

Phase 2.5 is done: `mlp-v12` returns HTTP 200 from both internal and gateway `/v2/models/mlp/infer`.

## Current Truth

Git on `fall@192.168.1.154:/home/fall/dev/ai_platform`:

```text
## main...origin/main
 M images/build-and-push.sh
 M monitoring/evidently-job/cronjob.yaml
 M monitoring/evidently-job/run.py
 M serving/inference-logger.yaml
?? AGENTS.md
?? serving/inference-logger/
```

Cluster:

```text
serving/inference-logger: 2/2 pods Running
serving/mlp-canary: READY=True, revision=mlp-v12
monitoring/evidently-mlp: configured, but latest runs still fail until monitoring-minio-creds is fixed
registry: mlplatform/inference-logger tags ph3-logger, latest
registry: mlplatform/evidently-job tags ph3-logger, be5fff5, latest
```

Verified:

```text
KServe gateway infer -> HTTP 200
inference-logger received POST /log/mlp/canary -> HTTP 200
MinIO inference-logs/mlp/canary/...jsonl objects were created
```

## Files Changed

- `serving/inference-logger/main.py`
  - FastAPI sink for KServe payload logger.
  - Writes one NDJSON object per request to `s3://inference-logs/<model>/<variant>/<date>/...jsonl`.
  - Normalizes `instances` from v1/v2/raw request shapes.
- `serving/inference-logger/Dockerfile`
- `serving/inference-logger/requirements.txt`
- `serving/inference-logger.yaml`
  - Deploys logger in `serving`.
  - Uses Pi4 MinIO endpoint `http://192.168.1.37:9000`.
- `images/build-and-push.sh`
  - Adds `inference-logger` image.
- `monitoring/evidently-job/run.py`
  - Falls back from missing `MODEL_VERSION=current` to the latest available `reference-data/<model>/<version>/reference.parquet`.
  - Parses logger-normalized records and KServe v2 `inputs[0].data`.
- `monitoring/evidently-job/cronjob.yaml`
  - Uses Pi4 MinIO endpoint.
  - No longer stores MinIO admin credentials in the manifest.

## Decisions

- Do not store Pi4 MinIO admin credentials in `monitoring/evidently-job/cronjob.yaml`.
- Evidently should use a least-privilege MinIO credential with:
  - read/list: `reference-data`, `inference-logs`
  - write: `drift-reports`
- `MODEL_VERSION=current` stays in the CronJob; code resolves it to latest available reference if the alias path is absent.
- Smoke/KFP runs should keep cache disabled unless explicitly testing cache behavior.

## Current Blocker

`evidently-mlp` now reaches MinIO but fails with:

```text
InvalidAccessKeyId
```

Reason: existing `monitoring/monitoring-minio-creds` Secret has credentials that Pi4 MinIO rejects.

Security note: attempts to write MinIO admin credentials, or to create and inject a new persistent MinIO user, were blocked by approval policy. The next user-approved action should be explicit:

```text
Approve creating a least-privilege MinIO user for the monitoring namespace,
limited to reference-data/inference-logs read and drift-reports write.
```

After approval, create/update `monitoring-minio-creds` with that limited user. Do not commit the secret material.

## Exact Next Steps

1. Get explicit approval for the limited MinIO monitoring credential.
2. Create the MinIO policy/user on Pi4 and update only the Kubernetes Secret `monitoring/monitoring-minio-creds`.
3. Run:

   ```bash
   kubectl -n monitoring delete job evidently-mlp-manual --ignore-not-found
   kubectl -n monitoring create job --from=cronjob/evidently-mlp evidently-mlp-manual
   kubectl -n monitoring wait --for=condition=complete job/evidently-mlp-manual --timeout=240s
   kubectl -n monitoring logs job/evidently-mlp-manual --all-containers=true --tail=240
   ```

4. Verify:

   ```bash
   kubectl -n monitoring exec deploy/pushgateway -- sh -c 'wget -qO- http://127.0.0.1:9091/metrics || true'
   ```

5. If metrics exist, push a high drift sample or wait for alert firing, then verify `ml-webhook /trigger` starts a `finetune_pipeline` run.

