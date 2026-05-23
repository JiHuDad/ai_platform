"""MLflow 의 'production' alias 에서 현재 모델의 storageUri / accuracy 를 조회.

fine-tune 시 base checkpoint 와 비교 기준치를 제공한다.
스칼라 3개를 NamedTuple 로 반환 — OutputPath(file) 대신 KFP v2 의 param output 사용.
"""
from typing import NamedTuple

from kfp import dsl


@dsl.component(
    base_image="kfp-registry:5000/mlplatform/trainer:latest",
)
def pull_production_model(
    model_name: str,
) -> NamedTuple("Outputs", [
    ("base_checkpoint_uri", str),
    ("production_accuracy", float),
    ("production_version", str),
]):
    import os
    from collections import namedtuple

    import mlflow
    from mlflow.tracking import MlflowClient

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    client = MlflowClient()

    mv = client.get_model_version_by_alias(model_name, "production")
    run = client.get_run(mv.run_id)
    metrics = run.data.metrics
    acc = float(metrics.get("test_accuracy") or metrics.get("val_acc") or 0.0)

    artifact = run.info.artifact_uri.rstrip("/") + "/model/state_dict.pt"
    storage_uri = artifact.replace("mlflow-artifacts:", "s3://mlflow-artifacts")

    print(f"[pull-prod] {model_name} v{mv.version} acc={acc:.4f} uri={storage_uri}")

    Outputs = namedtuple("Outputs", ["base_checkpoint_uri", "production_accuracy", "production_version"])
    return Outputs(storage_uri, acc, str(mv.version))
