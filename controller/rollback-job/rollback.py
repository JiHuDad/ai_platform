"""즉시 롤백 Job.

전략 (가장 빠른 path 우선):
  1) VirtualService weight 를 stable=100, canary=0 으로 강제.
  2) canary InferenceService 를 scale-to-zero (자원 회수).
  3) Grafana annotation API 로 사건 기록 (REASON, MODEL, ts).
  4) MLflow alias 는 변경하지 않음 — 'previous' 가 살아있어 재롤백 가능.

심각 상황 (stable 자체 장애):
  - REASON=stable_breach 라면 MinIO `serving-manifests/<model>/` 의 직전 스냅샷에서
    stable InferenceService 를 그대로 kubectl apply 하여 storageUri 를 이전 모델로 되돌린다.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import boto3
import httpx
import yaml
from kubernetes import client as k8s, config as k8s_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rollback")

MODEL = os.environ["MODEL_NAME"]
SERVING_NS = os.environ.get("SERVING_NS", "serving")
REASON = os.environ.get("REASON", "manual")
GRAFANA = os.environ.get("GRAFANA_URL", "http://monitoring-grafana.monitoring/api/annotations")
GRAFANA_TOKEN = os.environ.get("GRAFANA_TOKEN", "")

try:
    k8s_config.load_incluster_config()
except Exception:
    k8s_config.load_kube_config()
custom = k8s.CustomObjectsApi()


def fast_rollback():
    body = {"spec": {"http": [{
        "name": "weighted",
        "match": [
            {"uri": {"prefix": f"/v1/models/{MODEL}"}},
            {"uri": {"prefix": f"/v2/models/{MODEL}"}},
        ],
        "route": [
            {"destination": {"host": f"{MODEL}-stable-predictor.{SERVING_NS}.svc.cluster.local",
                             "port": {"number": 80}}, "weight": 100},
            {"destination": {"host": f"{MODEL}-canary-predictor.{SERVING_NS}.svc.cluster.local",
                             "port": {"number": 80}}, "weight": 0},
        ],
    }]}}
    custom.patch_namespaced_custom_object(
        group="networking.istio.io", version="v1beta1",
        namespace=SERVING_NS, plural="virtualservices", name=MODEL, body=body,
    )
    log.info("VS %s weight forced to 100/0", MODEL)

    body0 = {"spec": {"predictor": {"minReplicas": 0, "maxReplicas": 0}}}
    try:
        custom.patch_namespaced_custom_object(
            group="serving.kserve.io", version="v1beta1",
            namespace=SERVING_NS, plural="inferenceservices",
            name=f"{MODEL}-canary", body=body0,
        )
        log.info("canary scaled to zero")
    except k8s.exceptions.ApiException as e:
        log.warning("canary scale-to-zero failed: %s", e)


def deep_rollback_from_snapshot():
    """가장 최근 스냅샷의 stable-isvc.yaml 을 적용. stable 자체가 망가졌을 때만 사용."""
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )
    paginator = s3.get_paginator("list_objects_v2")
    snaps: list[str] = []
    for page in paginator.paginate(Bucket="serving-manifests", Prefix=f"{MODEL}/"):
        for it in page.get("Contents", []):
            if it["Key"].endswith("/stable-isvc.yaml"):
                snaps.append(it["Key"])
    if not snaps:
        log.error("no snapshot available — deep rollback aborted")
        return
    snaps.sort(reverse=True)
    # 첫번째는 *현재* (방금 만든 것일 수 있음) — 두번째가 직전.
    target_key = snaps[1] if len(snaps) > 1 else snaps[0]
    obj = s3.get_object(Bucket="serving-manifests", Key=target_key)["Body"].read()
    spec = yaml.safe_load(obj)
    log.info("applying snapshot %s", target_key)
    custom.patch_namespaced_custom_object(
        group="serving.kserve.io", version="v1beta1",
        namespace=SERVING_NS, plural="inferenceservices",
        name=f"{MODEL}-stable", body=spec,
    )


def annotate_grafana():
    if not GRAFANA_TOKEN:
        log.info("no GRAFANA_TOKEN — skip annotation")
        return
    payload = {
        "time": int(time.time() * 1000),
        "tags": ["rollback", MODEL, REASON],
        "text": f"Rollback executed for {MODEL} (reason={REASON})",
    }
    try:
        r = httpx.post(GRAFANA, json=payload,
                       headers={"Authorization": f"Bearer {GRAFANA_TOKEN}"}, timeout=5)
        log.info("grafana annotation: %s", r.status_code)
    except Exception as e:
        log.warning("grafana annotation failed: %s", e)


def main() -> int:
    log.info("rollback start: model=%s reason=%s ns=%s ts=%s",
             MODEL, REASON, SERVING_NS, datetime.now(timezone.utc).isoformat())
    fast_rollback()
    if REASON in ("stable_breach", "deep_rollback"):
        deep_rollback_from_snapshot()
    annotate_grafana()
    log.info("rollback complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
