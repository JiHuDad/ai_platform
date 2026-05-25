# AI Handoff - ai_platform

Snapshot: 2026-05-25 KST - Phase 3 drift-to-finetune-to-promote loop is now functionally through v13.

Before editing, read `CLAUDE.md`, `AGENTS.md`, this file, `docs/claude-last-diff-summary.md`, and `git diff`.

## Objective

Keep hardening Phase 3:

```text
KServe request -> inference-logger -> MinIO inference-logs
-> Evidently -> Pushgateway/Prometheus -> Alertmanager
-> ml-webhook /trigger -> finetune_pipeline
-> deploy canary -> promote -> MLflow aliases + stable serving
```

The original gate was: do not enter Phase 3 until internal/gateway predict returns HTTP 200 with a prediction body. That gate is now satisfied for KServe v2:

```bash
curl -H 'Host: mlp.mlplatform.local' \
  -H 'Content-Type: application/json' \
  -d '{"inputs":[{"name":"input-0","shape":[1,4],"datatype":"FP32","data":[[5.1,3.5,1.4,0.2]]}]}' \
  http://192.168.1.154/v2/models/mlp/infer
```

Latest result: HTTP 200 with `{"predictions":[2]}` in the response body.

## Current Truth

Remote repo:

```text
fall@192.168.1.154:/home/fall/dev/ai_platform
branch: main
uncommitted tracked changes:
  M controller/canary-job/promote.py
  M controller/webhook/deploy.yaml
  M controller/webhook/main.py
  M pipelines/components/preprocess.py
  M pipelines/components/trigger_promote_job.py
  M pipelines/finetune_pipeline.py
  M pipelines/kfp-rbac.yaml
  M scripts/e2e_smoke.sh
  M scripts/perturb_inference.py
untracked:
  ?? AGENTS.md
```

Cluster state after manual v13 promotion:

```text
serving/mlp-stable: READY=True, 2/2 predictor pods
serving/mlp-canary deployment: 0/0 replicas
serving/VirtualService mlp weights: stable=100 canary=0
serving/VirtualService labels: canary-revision=mlp-v13 stable-revision=mlp-v13
MLflow alias production=v13
MLflow alias previous=v12
MLflow alias staging=v13
```

Image and pipeline updates pushed to the local registry:

```text
kfp-registry:5000/mlplatform/ml-webhook:latest
kfp-registry:5000/mlplatform/canary-job:latest
latest canary-job digest observed: sha256:62a1555894698f7d8e6fdd025bc415bcc0adc6853eca107213283d729d296406
latest KFP finetune version: v20260525T092842Z
latest KFP finetune version id: 433b726c-a7cd-4518-a747-93c42a033263
```

## Files Changed

- `controller/webhook/main.py`
  - Fixed idempotency handling so alerts are marked only after successful pipeline/job submission.
  - Removed KFP server-side run filter that KFP 2.15 rejected.
  - Selects the latest finetune pipeline version from up to 100 versions.
  - Ignores non-drift alerts for `/trigger`.
  - Adds `BASE_DATASET_URI` to finetune params.
- `controller/webhook/deploy.yaml`
  - Adds `BASE_DATASET_URI`.
  - Adds `allow-ml-webhook-to-ml-pipeline` NetworkPolicy in `kubeflow`.
  - Extends `rollback-runner` RBAC for canary deployment scale-to-zero.
- `pipelines/components/preprocess.py`
  - Writes KFP output artifacts both to `OutputPath` and the launcher's `minio://` local artifact path.
- `pipelines/finetune_pipeline.py`
  - Disables caching for finetune tasks via `run_once(...)`.
- `pipelines/components/trigger_promote_job.py`
  - Uses the Pi MLflow endpoint fallback `http://192.168.1.37:5001`.
- `pipelines/kfp-rbac.yaml`
  - Allows `kubeflow:pipeline-runner` to create/get/list/watch `jobs.batch` in `serving`.
- `controller/canary-job/promote.py`
  - Adds configurable `PROMOTE_STEPS` and `SLO_POLL_SECONDS`.
  - Avoids routing stable traffic until `mlp-stable` is Ready.
  - Creates/updates stable with stable logger URL and revision labels.
  - Waits for stable Ready before switching traffic to stable.
  - Scales canary Deployment to 0 after promotion.
- `scripts/e2e_smoke.sh`
  - Uses gateway + Host header + KServe v2 `/v2/models/<model>/infer`.
- `scripts/perturb_inference.py`
  - Sends KServe v2 `inputs` payload and supports `--host-header`.

## Decisions

- Current serving protocol is KServe v2. V1 `instances` payloads to `/v1/models/mlp:predict` fail with TorchServe `KeyError: 'inputs'`; tests and load scripts should use v2.
- Do not promote if v2 predict is not HTTP 200 with a prediction body.
- Monitoring MinIO credentials are least-privilege, not admin:
  - read/list: `reference-data`, `inference-logs`
  - write: `drift-reports`
- Keep finetune task caching disabled for drift-triggered runs.
- For first promotion when no stable exists, keep traffic on canary until stable is created and Ready; then switch stable=100/canary=0.
- Do not touch untracked `AGENTS.md` unless the user asks.

## Phase 3 자동 E2E green-light (2026-05-25 KST late)

Codex 의 Phase 3 stabilize commit (2610fda, 277d76a) 후 자동 루프 *끝까지* 검증:

```text
drift inject (200 req) → inference-logger NDJSON 적재 → Evidently job
  → drift_share=1.000 feature_drift_count=4 → Pushgateway mlp_drift_score=1
  → Prometheus scrape OK → Alertmanager MLPDriftHigh state=active
  → ml-webhook /trigger (manual call, alert firing 30m 대기 우회)
  → finetune-mlp-1779704542 KFP run = SUCCEEDED (10 pods Completed)
  → trigger_promote_job → promote-mlp-v13-20260525t102519 Job RUNNING
```

새 MLflow version 안 만들어짐 (v13 그대로) — *의도된 동작*: labeled inference logs (`s3://inference-logs/<model>/labeled/`) 부재 → assemble_finetune_dataset 가 base only → register_to_mlflow 의 dedup logic (`search_model_versions where dataset_hash + git_sha 일치`) 이 v13 reuse. 진짜 retrain 위해선 labeling pipeline 추가 필요 (Phase 3.5).

## Current Bugs / Risks

- ~~`mlp-finetune-jkkrn` Failed~~ → ✅ 새 run `finetune-mlp-1779704542` Succeeded.
- ✅ **promote default dwell 전체 cycle 통과** (`promote-mlp-v13-20260525t102519` Completions=1/1 DURATION=55m): 10/50/100% × 900/1800/600s, MLflow alias rotation, stable Ready, VS=100/0, canary scale-to-zero.
- ⚠️ **SLO gate metric source 한계**: `promote.py` 의 SLO query 가 `istio_requests_total{destination_app=...}` 사용. predictor pod 에 Istio sidecar 미주입 → metric 부재 → SLO check 가 항상 zero 통과. serving ns 에 `istio-injection=enabled` 라벨 박아도 KServe Raw 모드의 webhook namespaceSelector 충돌로 sidecar 안 들어감. 진짜 fix 옵션:
  - KServe ConfigMap 의 sidecar opt-in (storage-initializer 와 init order 검증 필요)
  - 또는 SLO query 를 KServe 자체 metric (kserve-predictors ServiceMonitor) 로 변경
  - 또는 ingressgateway metric (`source_workload="istio-ingressgateway"`) 으로
  - 우리 toy 환경의 진짜 가치 한계 — production traffic 자리.
- ✅ **Disk cleanup**: 90% → 84% (`docker image prune -a` + 183 succeeded pods 삭제, 12.41GB 회수).
- ✅ Load test (정상 traffic 100 req via gateway): ok=100/0 — gateway routing OK.
- The manual promote Job used `PROMOTE_STEPS=100:60` for fast validation. Production/default promote still uses `10%/50%/100%` with 900/1800/600 second dwell.
- Prometheus SLO queries returned zeros in the manual promotion because there was little/no active traffic. Add sustained traffic before treating SLO gates as load-tested.
- `mlp-canary` InferenceService remains `Ready=True` even though its Deployment is scaled to 0. This is acceptable for rollback staging, but dashboard readers may find it confusing.
- Disk usage on `leaf007` was observed around 88.6% in TorchServe metrics. Not blocking now, but cleanup is still advisable before repeated training/image builds.

## Failing Commands / Historical Failures

These are expected historical failures, not the current final state:

```text
curl /v1/models/mlp:predict with {"instances": ...}
-> HTTP 500, TorchServe kservev2 envelope KeyError: 'inputs'
```

```text
KFP trigger-promote-job in mlp-finetune-jkkrn
-> 403: system:serviceaccount:kubeflow:pipeline-runner cannot create jobs.batch in serving
```

```text
manual promote job with MLFLOW_TRACKING_URI=http://mlflow.mlflow:5000
-> DNS failure for mlflow.mlflow
```

## Verified Commands

```bash
python3 -m py_compile controller/canary-job/promote.py pipelines/components/trigger_promote_job.py scripts/perturb_inference.py
bash -n scripts/e2e_smoke.sh
kubectl apply -f pipelines/kfp-rbac.yaml
kubectl apply -f controller/webhook/deploy.yaml
./pipelines/compile-and-register.sh
./scripts/e2e_smoke.sh 3
```

Manual v13 promotion completed:

```text
MLflow alias production=13 (previous->12)
created stable from canary spec
InferenceService mlp-stable is Ready
VirtualService mlp weight stable=100 canary=0
canary scaled to zero - promotion complete
```

## Exact Next Steps

1. Commit the current tracked changes if review is acceptable. Leave untracked `AGENTS.md` alone unless instructed.
2. Run a fresh end-to-end drift trigger after the RBAC and pipeline fixes:

   ```bash
   cd /home/fall/dev/ai_platform
   ./scripts/e2e_smoke.sh 3
   ./scripts/e2e_smoke.sh 4
   kubectl -n monitoring delete job evidently-mlp-manual --ignore-not-found
   kubectl -n monitoring create job --from=cronjob/evidently-mlp evidently-mlp-manual
   kubectl -n monitoring wait --for=condition=complete job/evidently-mlp-manual --timeout=300s
   kubectl -n monitoring logs job/evidently-mlp-manual --all-containers=true --tail=240
   ```

3. Verify Pushgateway/Prometheus drift metrics and Alertmanager routing.
4. Trigger `/trigger` again and confirm the new KFP finetune run succeeds all the way through `trigger-promote-job`.
5. Let the default promote dwell run under real traffic, or explicitly set a short `PROMOTE_STEPS` only for a controlled test.
6. Clean disk on `leaf007` before repeated image builds/training if usage remains near 90%.
