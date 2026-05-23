"""KFP 파이프라인 마지막 단계 — canary step-up Job 을 K8s 에 제출.

promote.py 를 실행하는 Job 을 만들어 비동기로 step-up 시작. KFP run 은 즉시 성공 종료.
(KFP 안에 sleep 1시간 짜리를 두면 파이프라인 락이 길어지므로 별도 Job 으로 분리.)
"""
from kfp import dsl


@dsl.component(
    base_image="kfp-registry:5000/mlplatform/trainer:latest",
)
def trigger_promote_job(
    model_name: str,
    new_model_version: str,
    serving_ns: str,
) -> None:
    import os
    from datetime import datetime

    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    batch = client.BatchV1Api()

    ts = datetime.utcnow().strftime("%Y%m%dt%H%M%S")
    job_name = f"promote-{model_name}-v{new_model_version}-{ts}"

    job = client.V1Job(
        metadata=client.V1ObjectMeta(
            name=job_name, namespace=serving_ns,
            labels={"app": "promote", "model": model_name, "version": new_model_version},
        ),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=86400,
            backoff_limit=0,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "promote", "model": model_name}),
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    service_account_name="rollback-runner",
                    containers=[client.V1Container(
                        name="promote",
                        image=os.environ.get("PROMOTE_IMAGE",
                                             "kfp-registry:5000/mlplatform/canary-job:latest"),
                        env=[
                            client.V1EnvVar(name="MODEL_NAME", value=model_name),
                            client.V1EnvVar(name="NEW_MODEL_VERSION", value=new_model_version),
                            client.V1EnvVar(name="SERVING_NS", value=serving_ns),
                            client.V1EnvVar(name="PROMETHEUS_URL",
                                            value="http://monitoring-kube-prometheus-prometheus.monitoring:9090"),
                            client.V1EnvVar(name="MLFLOW_TRACKING_URI",
                                            value=os.environ.get("MLFLOW_TRACKING_URI",
                                                                 "http://mlflow.mlflow:5000")),
                        ],
                        resources=client.V1ResourceRequirements(
                            requests={"cpu": "100m", "memory": "256Mi"},
                            limits={"cpu": "1", "memory": "512Mi"},
                        ),
                    )],
                ),
            ),
        ),
    )
    batch.create_namespaced_job(serving_ns, job)
    print(f"[trigger-promote] Job {job_name} created in {serving_ns}")
