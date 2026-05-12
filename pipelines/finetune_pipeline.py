"""Drift 트리거 시 자동 실행되는 fine-tune 파이프라인.

흐름:
  pull_production_model → assemble_finetune_dataset → preprocess → train (base_ckpt) →
  evaluate (현 prod acc 가 baseline) → register_to_mlflow(Staging) →
  deploy_canary(weight=10) → trigger_promote_job (비동기 step-up).
"""
from kfp import dsl

from pipelines.components.assemble_finetune_dataset import assemble_finetune_dataset
from pipelines.components.deploy_canary import deploy_canary
from pipelines.components.evaluate import evaluate
from pipelines.components.preprocess import preprocess
from pipelines.components.pull_production_model import pull_production_model
from pipelines.components.register_to_mlflow import register_to_mlflow
from pipelines.components.train_mlp import train_mlp
from pipelines.components.trigger_promote_job import trigger_promote_job


@dsl.pipeline(name="mlp-finetune", description="Drift 트리거 fine-tune → Canary 자동 step-up.")
def finetune_pipeline(
    model_name: str = "mlp",
    base_dataset_uri: str = "s3://datasets/demo/iris/latest/",
    window_hours: int = 24,
    hidden_dims: str = "128,64",
    epochs: int = 10,                     # fine-tune 은 짧게
    lr: float = 3e-4,
    batch_size: int = 256,
    git_sha: str = "auto",
    triggered_by: str = "drift",
):
    prod = pull_production_model(model_name=model_name)
    ds = assemble_finetune_dataset(
        model_name=model_name,
        base_dataset_uri=base_dataset_uri,
        window_hours=window_hours,
    )
    prep = preprocess(
        input_dir=ds.outputs["output_dir"],
        model_name=model_name,
        model_version="finetune",
    )
    tr = train_mlp(
        train_npz=prep.outputs["train_out"],
        val_npz=prep.outputs["val_out"],
        hidden_dims=hidden_dims,
        epochs=epochs,
        lr=lr,
        batch_size=batch_size,
        base_checkpoint_uri=prod.outputs["base_checkpoint_uri_out"],
    )
    ev = evaluate(
        model_dir=tr.outputs["model_out"],
        test_npz=prep.outputs["test_out"],
        baseline_accuracy=prod.outputs["production_accuracy_out"],
    )
    with dsl.If(ev.outputs["passed"] == "true", name="fine-tune-improved"):
        reg = register_to_mlflow(
            model_dir=tr.outputs["model_out"],
            metrics=ev.outputs["metrics_out"],
            model_name=model_name,
            dataset_uri=ds.outputs["new_dataset_uri_out"],
            dataset_hash=ds.outputs["dataset_hash_out"],
            git_sha=git_sha,
            kfp_run_id=dsl.PIPELINE_JOB_NAME_PLACEHOLDER,
            triggered_by=triggered_by,
        )
        dep = deploy_canary(
            model_name=model_name,
            model_version=reg.outputs["model_version_out"],
            storage_uri=reg.outputs["model_uri_out"],
            initial_canary_weight=10,
        ).after(reg)
        trigger_promote_job(
            model_name=model_name,
            new_model_version=reg.outputs["model_version_out"],
            serving_ns="serving",
        ).after(dep)


if __name__ == "__main__":
    from kfp.compiler import Compiler
    Compiler().compile(finetune_pipeline, "finetune_pipeline.yaml")
