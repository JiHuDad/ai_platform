"""MLflow 의 'production' alias 에서 현재 모델의 storageUri / accuracy 를 조회.

fine-tune 시 base checkpoint 와 비교 기준치를 제공한다.
"""
from kfp import dsl


@dsl.component(
    base_image="harbor.mlplatform.local/mlplatform/trainer:latest",
)
def pull_production_model(
    model_name: str,
    base_checkpoint_uri_out: dsl.OutputPath("String"),
    production_accuracy_out: dsl.OutputPath("String"),
    production_version_out: dsl.OutputPath("String"),
) -> None:
    import json
    import os
    from pathlib import Path

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

    Path(base_checkpoint_uri_out).write_text(storage_uri)
    Path(production_accuracy_out).write_text(str(acc))
    Path(production_version_out).write_text(str(mv.version))
    print(f"[pull-prod] {model_name} v{mv.version} acc={acc:.4f} uri={storage_uri}")
