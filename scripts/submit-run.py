"""KFP run 제출 — repeatable, heredoc 대신.

Usage:
  .venv/bin/python scripts/submit-run.py \\
    --name train-smoke-8-mar \\
    --git-sha p2.5-mar \\
    [--pipeline pipelines/train_pipeline.yaml] \\
    [--dataset s3://datasets/demo/iris/20260523-v1/] \\
    [--epochs 5]
"""
import argparse
from kfp.client import Client


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pipeline", default="pipelines/train_pipeline.yaml")
    p.add_argument("--experiment", default="smoke")
    p.add_argument("--name", required=True, help="run name (e.g. train-smoke-8-mar)")
    p.add_argument("--git-sha", required=True)
    p.add_argument("--dataset", default="s3://datasets/demo/iris/20260523-v1/")
    p.add_argument("--model", default="mlp")
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--baseline-acc", type=float, default=0.0)
    p.add_argument("--triggered-by", default="manual")
    p.add_argument("--host", default="http://localhost:8888")
    a = p.parse_args()

    c = Client(host=a.host)
    run = c.create_run_from_pipeline_package(
        pipeline_file=a.pipeline,
        arguments={
            "dataset_uri": a.dataset,
            "model_name": a.model,
            "epochs": a.epochs,
            "baseline_accuracy": a.baseline_acc,
            "git_sha": a.git_sha,
            "triggered_by": a.triggered_by,
        },
        experiment_name=a.experiment,
        run_name=a.name,
    )
    print(f"RUN_ID: {run.run_id}")
    print(f"URL:    {a.host}/#/runs/details/{run.run_id}")


if __name__ == "__main__":
    main()
