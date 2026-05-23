"""신규 학습 파이프라인 (from scratch).

흐름:
  data_ingest → preprocess → train_mlp → evaluate → (gate) → register_to_mlflow → deploy_canary
canary 배포 후엔 별도 `promote_pipeline` 이 step-up 을 수행한다.
"""
from kfp import dsl

from pipelines.components.data_ingest import data_ingest
from pipelines.components.preprocess import preprocess
from pipelines.components.train_mlp import train_mlp
from pipelines.components.evaluate import evaluate
from pipelines.components.register_to_mlflow import register_to_mlflow
from pipelines.components.deploy_canary import deploy_canary


@dsl.pipeline(
    name="mlp-train",
    description="MLP 신규 학습 → Staging → Canary 배포까지.",
)
def train_pipeline(
    dataset_uri: str,
    model_name: str = "mlp",
    model_version: str = "1",
    hidden_dims: str = "128,64",
    epochs: int = 30,
    lr: float = 1e-3,
    batch_size: int = 256,
    baseline_accuracy: float = 0.0,         # 최초 학습은 0 (절대 통과)
    git_sha: str = "unknown",
    triggered_by: str = "manual",
    initial_canary_weight: int = 10,
):
    ingest = data_ingest(dataset_uri=dataset_uri)
    prep = preprocess(
        input_dir=ingest.outputs["output_dir"],
        model_name=model_name,
        model_version=model_version,
    )
    tr = train_mlp(
        train_npz=prep.outputs["train_out"],
        val_npz=prep.outputs["val_out"],
        hidden_dims=hidden_dims,
        epochs=epochs,
        lr=lr,
        batch_size=batch_size,
        base_checkpoint_uri="",
    )
    ev = evaluate(
        model_dir=tr.outputs["model_out"],
        test_npz=prep.outputs["test_out"],
        baseline_accuracy=baseline_accuracy,
    )
    with dsl.If(ev.outputs["passed"] == "true", name="gate-passed"):
        reg = register_to_mlflow(
            model_dir=tr.outputs["model_out"],
            metrics=ev.outputs["metrics_out"],
            model_name=model_name,
            dataset_uri=dataset_uri,
            dataset_hash=ingest.outputs["dataset_hash"],
            git_sha=git_sha,
            kfp_run_id=dsl.PIPELINE_JOB_NAME_PLACEHOLDER,
            triggered_by=triggered_by,
            base_dataset_uri="",   # train 은 자기 자신이 base.
        )
        deploy_canary(
            model_name=model_name,
            model_version=reg.outputs["model_version_out"],
            storage_uri=reg.outputs["model_uri_out"],
            initial_canary_weight=initial_canary_weight,
        ).after(reg)


if __name__ == "__main__":
    from kfp.compiler import Compiler
    Compiler().compile(train_pipeline, "train_pipeline.yaml")
