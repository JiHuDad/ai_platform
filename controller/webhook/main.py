"""Alertmanager webhook 수신기.

엔드포인트:
  POST /trigger    — drift 알림 → finetune_pipeline KFP run 생성
  POST /rollback   — serving SLO 위반 → rollback Job 생성

중복 방지:
  같은 (model, alertname) 에 대해 활성 KFP run 이 있으면 신규 트리거 skip.
  최근 1시간 내 동일 알림은 idempotency cache 로 차단.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from kfp.client import Client as KFPClient
from kubernetes import client as k8s, config as k8s_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ml-webhook")

KFP_HOST = os.environ.get("KFP_HOST", "http://ml-pipeline.kubeflow.svc.cluster.local:8888")
KFP_NAMESPACE = os.environ.get("KFP_NAMESPACE", "kubeflow")
FINETUNE_PIPELINE_ID = os.environ.get("FINETUNE_PIPELINE_ID", "")
FINETUNE_EXPERIMENT = os.environ.get("FINETUNE_EXPERIMENT", "finetune-auto")
ROLLBACK_IMAGE = os.environ.get("ROLLBACK_IMAGE", "kfp-registry:5000/mlplatform/rollback-job:latest")
SERVING_NAMESPACE = os.environ.get("SERVING_NAMESPACE", "serving")

app = FastAPI()
_idem: dict[tuple[str, str], float] = {}
IDEM_TTL_S = 60 * 60

try:
    k8s_config.load_incluster_config()
except Exception:
    k8s_config.load_kube_config()
_batch = k8s.BatchV1Api()


def _idempotency_check(key: tuple[str, str]) -> bool:
    """True 면 신규 — False 면 최근 같은 알림 처리됨."""
    now = time.time()
    # cache 청소
    for k, ts in list(_idem.items()):
        if now - ts > IDEM_TTL_S:
            _idem.pop(k, None)
    if key in _idem:
        return False
    _idem[key] = now
    return True


def _kfp() -> KFPClient:
    return KFPClient(host=KFP_HOST)


def _has_active_finetune_run(client: KFPClient, model: str) -> bool:
    """동일 모델에 대해 Running 상태 run 이 있는지 확인."""
    exp = client.create_experiment(FINETUNE_EXPERIMENT)
    runs = client.list_runs(
        experiment_id=exp.experiment_id,
        page_size=20,
        filter='{"predicates":[{"key":"state","op":"EQUALS","string_value":"RUNNING"}]}',
    )
    # 단순화: run name 에 모델명 포함 컨벤션 사용 (display_name 에 model substring).
    for r in (runs.runs or []):
        if model in (r.display_name or ""):
            return True
    return False


@app.post("/trigger")
async def trigger(req: Request) -> dict[str, Any]:
    """Alertmanager 의 drift 알림 → finetune 파이프라인 실행."""
    payload = await req.json()
    alerts = payload.get("alerts", [])
    if not alerts:
        raise HTTPException(400, "no alerts")

    fired = [a for a in alerts if a.get("status") == "firing"]
    triggered: list[dict[str, str]] = []

    for a in fired:
        labels = a.get("labels", {})
        model = labels.get("model", "mlp")
        alertname = labels.get("alertname", "unknown")
        if not _idempotency_check((model, alertname)):
            log.info("idempotent skip: %s/%s", model, alertname)
            continue

        client = _kfp()
        if _has_active_finetune_run(client, model):
            log.info("active finetune run exists for %s, skipping", model)
            continue

        run_name = f"finetune-{model}-{int(time.time())}"
        run = client.run_pipeline(
            experiment_id=client.create_experiment(FINETUNE_EXPERIMENT).experiment_id,
            job_name=run_name,
            pipeline_id=FINETUNE_PIPELINE_ID,
            params={
                "model_name": model,
                "triggered_by": "drift",
                "git_sha": os.environ.get("GIT_SHA", "auto"),
            },
        )
        log.info("submitted finetune run: %s (%s)", run_name, run.run_id)
        triggered.append({"model": model, "run_id": run.run_id, "run_name": run_name})

    return {"triggered": triggered}


@app.post("/rollback")
async def rollback(req: Request) -> dict[str, Any]:
    """Serving SLO 위반 → rollback Job 즉시 생성."""
    payload = await req.json()
    alerts = payload.get("alerts", [])
    rolled: list[dict[str, str]] = []
    for a in alerts:
        if a.get("status") != "firing":
            continue
        labels = a.get("labels", {})
        model = labels.get("model") or labels.get("destination_app", "mlp").replace("-canary", "").replace("-stable", "")
        if not _idempotency_check((model, "rollback")):
            log.info("rollback dedupe skip: %s", model)
            continue

        job_name = f"rollback-{model}-{int(time.time())}"
        job = k8s.V1Job(
            metadata=k8s.V1ObjectMeta(name=job_name, namespace=SERVING_NAMESPACE,
                                     labels={"app": "rollback", "model": model}),
            spec=k8s.V1JobSpec(
                ttl_seconds_after_finished=3600,
                backoff_limit=0,
                template=k8s.V1PodTemplateSpec(
                    metadata=k8s.V1ObjectMeta(labels={"app": "rollback", "model": model}),
                    spec=k8s.V1PodSpec(
                        restart_policy="Never",
                        service_account_name="rollback-runner",
                        containers=[k8s.V1Container(
                            name="rollback",
                            image=ROLLBACK_IMAGE,
                            env=[
                                k8s.V1EnvVar(name="MODEL_NAME", value=model),
                                k8s.V1EnvVar(name="SERVING_NS", value=SERVING_NAMESPACE),
                                k8s.V1EnvVar(name="REASON", value=labels.get("alertname", "slo_breach")),
                            ],
                            env_from=[k8s.V1EnvFromSource(
                                secret_ref=k8s.V1SecretEnvSource(name="minio-s3-creds"))],
                            resources=k8s.V1ResourceRequirements(
                                requests={"cpu": "50m", "memory": "128Mi"},
                                limits={"cpu": "500m", "memory": "512Mi"},
                            ),
                        )],
                    ),
                ),
            ),
        )
        _batch.create_namespaced_job(SERVING_NAMESPACE, job)
        log.info("submitted rollback job: %s", job_name)
        rolled.append({"model": model, "job": job_name})

    return {"rollback": rolled}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
