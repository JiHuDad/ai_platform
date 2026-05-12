"""Canary step-up 상태머신.

각 단계마다:
  1) VirtualService weight 를 patch.
  2) dwell 시간 동안 대기.
  3) Prometheus 로 SLO 게이트 평가.
  4) 통과 → 다음 단계. 실패 → rollback (VirtualService weight=0, MLflow alias 유지).

마지막 단계 통과 시:
  - MLflow `production` alias 를 새 버전으로 옮기고, 기존 production 은 `previous` 로 백업.
  - stable InferenceService 의 storageUri 를 새 버전으로 업데이트.
  - canary InferenceService 는 보존(scale-to-zero) — 즉시 재롤백 가능.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass

import httpx
import mlflow
from kubernetes import client as k8s, config as k8s_config
from mlflow.tracking import MlflowClient
from prometheus_api_client import PrometheusConnect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("canary-promote")

MODEL = os.environ["MODEL_NAME"]
NEW_VERSION = os.environ["NEW_MODEL_VERSION"]
SERVING_NS = os.environ.get("SERVING_NS", "serving")
PROMETHEUS = os.environ.get("PROMETHEUS_URL", "http://monitoring-kube-prometheus-prometheus.monitoring:9090")
MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow.mlflow:5000")

mlflow.set_tracking_uri(MLFLOW_URI)
prom = PrometheusConnect(url=PROMETHEUS, disable_ssl=True)

try:
    k8s_config.load_incluster_config()
except Exception:
    k8s_config.load_kube_config()
custom = k8s.CustomObjectsApi()


@dataclass
class Step:
    canary: int
    dwell_s: int
    label: str


STEPS = [
    Step(canary=10, dwell_s=900,  label="10%"),
    Step(canary=50, dwell_s=1800, label="50%"),
    Step(canary=100, dwell_s=600, label="100%"),
]


def patch_weight(canary: int):
    stable = 100 - canary
    body = {
        "spec": {
            "http": [{
                "name": "weighted",
                "match": [
                    {"uri": {"prefix": f"/v1/models/{MODEL}"}},
                    {"uri": {"prefix": f"/v2/models/{MODEL}"}},
                ],
                "route": [
                    {"destination": {"host": f"{MODEL}-stable-predictor.{SERVING_NS}.svc.cluster.local",
                                     "port": {"number": 80}}, "weight": stable},
                    {"destination": {"host": f"{MODEL}-canary-predictor.{SERVING_NS}.svc.cluster.local",
                                     "port": {"number": 80}}, "weight": canary},
                ],
            }]
        }
    }
    custom.patch_namespaced_custom_object(
        group="networking.istio.io", version="v1beta1",
        namespace=SERVING_NS, plural="virtualservices",
        name=MODEL, body=body,
    )
    log.info("VirtualService %s weight stable=%d canary=%d", MODEL, stable, canary)


def slo_pass() -> tuple[bool, dict]:
    """현재 canary 의 SLO 충족 여부 확인."""
    # canary 쪽 5xx ratio, p95 latency, stable 대비 비교.
    q_err = f'''
      sum(rate(istio_requests_total{{destination_service_namespace="{SERVING_NS}",destination_app="{MODEL}-canary",response_code=~"5.."}}[5m]))
      /
      ignoring() sum(rate(istio_requests_total{{destination_service_namespace="{SERVING_NS}",destination_app="{MODEL}-canary"}}[5m]))
    '''
    q_p95_canary = f'''
      histogram_quantile(0.95, sum by (le) (rate(istio_request_duration_milliseconds_bucket{{destination_service_namespace="{SERVING_NS}",destination_app="{MODEL}-canary"}}[5m])))
    '''
    q_p95_stable = f'''
      histogram_quantile(0.95, sum by (le) (rate(istio_request_duration_milliseconds_bucket{{destination_service_namespace="{SERVING_NS}",destination_app="{MODEL}-stable"}}[5m])))
    '''
    err = _scalar(q_err) or 0.0
    p95_c = _scalar(q_p95_canary) or 0.0
    p95_s = _scalar(q_p95_stable) or 1.0
    ratio = p95_c / max(p95_s, 1.0)
    metrics = {"5xx_ratio": err, "p95_canary_ms": p95_c, "p95_stable_ms": p95_s, "latency_ratio": ratio}

    ok = (err < 0.005) and (ratio < 1.2 or p95_c < 100)
    return ok, metrics


def _scalar(q: str) -> float | None:
    try:
        r = prom.custom_query(query=q)
        if not r:
            return None
        return float(r[0]["value"][1])
    except Exception as e:
        log.warning("prom query failed: %s", e)
        return None


def rollback():
    log.error("SLO failed — rolling back canary to weight=0")
    patch_weight(0)
    # canary InferenceService 는 보존 (재시도 위해).
    sys.exit(2)


def promote_alias_and_stable_isvc():
    """canary 가 모든 단계를 통과 → production alias 갱신 + stable storageUri 교체."""
    cli = MlflowClient()
    try:
        cur_prod = cli.get_model_version_by_alias(MODEL, "production")
        cli.set_registered_model_alias(MODEL, "previous", cur_prod.version)
    except Exception:
        log.info("no existing production alias — first promotion")
    cli.set_registered_model_alias(MODEL, "production", NEW_VERSION)
    log.info("MLflow alias production=%s (previous→%s)", NEW_VERSION,
             getattr(cur_prod, "version", "none") if "cur_prod" in dir() else "none")

    # stable InferenceService 의 storageUri 를 새 버전으로 교체.
    new_uri = cli.get_model_version(MODEL, NEW_VERSION).source.replace("mlflow-artifacts:", "s3://mlflow-artifacts")
    body = {"spec": {"predictor": {"model": {"storageUri": new_uri}}}}
    try:
        custom.patch_namespaced_custom_object(
            group="serving.kserve.io", version="v1beta1",
            namespace=SERVING_NS, plural="inferenceservices",
            name=f"{MODEL}-stable", body=body,
        )
        log.info("stable InferenceService updated to %s", new_uri)
    except k8s.exceptions.ApiException as e:
        if e.status == 404:
            # stable 이 아직 없으면 canary 의 spec 을 stable 이름으로 복제 생성
            canary = custom.get_namespaced_custom_object(
                group="serving.kserve.io", version="v1beta1",
                namespace=SERVING_NS, plural="inferenceservices", name=f"{MODEL}-canary",
            )
            spec = canary["spec"]
            new = {
                "apiVersion": "serving.kserve.io/v1beta1",
                "kind": "InferenceService",
                "metadata": {"name": f"{MODEL}-stable", "namespace": SERVING_NS,
                             "annotations": canary.get("metadata", {}).get("annotations", {})},
                "spec": spec,
            }
            custom.create_namespaced_custom_object(
                group="serving.kserve.io", version="v1beta1",
                namespace=SERVING_NS, plural="inferenceservices", body=new,
            )
            log.info("created stable from canary spec")
        else:
            raise

    # 트래픽 100% stable 로 복귀, canary scale to 0
    patch_weight(0)
    body0 = {"spec": {"predictor": {"minReplicas": 0, "maxReplicas": 0}}}
    custom.patch_namespaced_custom_object(
        group="serving.kserve.io", version="v1beta1",
        namespace=SERVING_NS, plural="inferenceservices",
        name=f"{MODEL}-canary", body=body0,
    )
    log.info("canary scaled to zero — promotion complete")


def main() -> int:
    for i, step in enumerate(STEPS, 1):
        log.info("==== step %d/%d: canary=%s, dwell=%ds", i, len(STEPS), step.label, step.dwell_s)
        patch_weight(step.canary)
        # warm-up 후 SLO 확인을 위해 dwell 동안 폴링.
        deadline = time.time() + step.dwell_s
        last: dict = {}
        while time.time() < deadline:
            time.sleep(60)
            ok, last = slo_pass()
            log.info("slo check: ok=%s metrics=%s", ok, json.dumps(last))
            if not ok:
                rollback()
        log.info("step %d passed: %s", i, json.dumps(last))
    promote_alias_and_stable_isvc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
