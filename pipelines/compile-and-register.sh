#!/usr/bin/env bash
# 파이프라인 컴파일 → KFP 에 등록 → pipeline_id 를 ConfigMap 으로 노출.
# idempotent: 이름 같은 파이프라인이 이미 있으면 새 version 만 추가.
#
# 전제: leaf007 의 .venv/ 가 kfp/kfp-kubernetes 갖추고 있고, KFP_HOST 가 도달 가능.
#       (in-cluster 가 아니면 `kubectl -n kubeflow port-forward svc/ml-pipeline 8888:8888` 먼저.)
set -euo pipefail
cd "$(dirname "$0")/.."

VENV="${VENV:-.venv}"
KFP_HOST="${KFP_HOST:-http://localhost:8888}"
NS="${NS:-mlops}"

"${VENV}/bin/python" - <<PY >/tmp/pipeline-ids.txt
from datetime import datetime, timezone
from kfp.client import Client
from kfp.compiler import Compiler
from pipelines.train_pipeline import train_pipeline
from pipelines.finetune_pipeline import finetune_pipeline

# 1) compile — yaml 은 코드 옆 (pipelines/) 에 떨어진다.
Compiler().compile(train_pipeline,    "pipelines/train_pipeline.yaml")
Compiler().compile(finetune_pipeline, "pipelines/finetune_pipeline.yaml")
print("[compile] OK", flush=True)

# 2) upload (create or new-version)
c = Client(host="${KFP_HOST}")

def upload(name: str, path: str) -> str:
    pid = None
    for p in (c.list_pipelines(page_size=100).pipelines or []):
        if p.display_name == name:
            pid = p.pipeline_id
            break
    ts = datetime.now(timezone.utc).strftime("v%Y%m%dT%H%M%SZ")
    if pid:
        c.upload_pipeline_version(
            pipeline_package_path=path,
            pipeline_version_name=ts,
            pipeline_id=pid,
        )
        print(f"[upload] {name}: new version {ts} on {pid}", flush=True)
    else:
        v = c.upload_pipeline(pipeline_package_path=path, pipeline_name=name)
        pid = v.pipeline_id
        print(f"[upload] {name}: created pipeline {pid}", flush=True)
    return pid

train_id = upload("mlp-train",    "pipelines/train_pipeline.yaml")
ft_id    = upload("mlp-finetune", "pipelines/finetune_pipeline.yaml")
# 마지막 두 줄: bash 가 파싱 (TRAIN_ID, FT_ID 순)
print(train_id)
print(ft_id)
PY

# python heredoc 의 *마지막 두 줄* 만 ID. 앞 [compile]/[upload] 로그는 stdout 에 같이 흘러갔는데
# 우리는 /tmp/pipeline-ids.txt 로 redirect 했다 → 화면에는 안 나옴. 진행 보고 싶으면 그 파일 cat.
cat /tmp/pipeline-ids.txt   # 진행 로그 보여주기
TRAIN_ID=$(tail -2 /tmp/pipeline-ids.txt | head -1)
FT_ID=$(tail -1 /tmp/pipeline-ids.txt)

[ -n "${TRAIN_ID}" ] && [ -n "${FT_ID}" ] || { echo "[err] upload failed"; exit 1; }

kubectl -n "${NS}" create configmap pipeline-ids \
  --from-literal=train="${TRAIN_ID}" \
  --from-literal=finetune="${FT_ID}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "[ok] train=${TRAIN_ID} finetune=${FT_ID} → ConfigMap ${NS}/pipeline-ids"
