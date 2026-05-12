"""MLflow Model Registry 에 등록 + lineage 태그 표준화.

표준 태그 (모든 모델 버전에 반드시):
  - dataset_uri, dataset_hash, git_sha, kfp_run_id, triggered_by

새 버전은 alias 'staging' 으로 시작. canary 통과 시 promote 파이프라인이 'production' 으로 옮긴다.
"""
from kfp import dsl


@dsl.component(
    base_image="harbor.mlplatform.local/mlplatform/trainer:latest",
)
def register_to_mlflow(
    model_dir: dsl.InputPath("Model"),
    metrics: dsl.InputPath("Metrics"),
    model_name: str,
    dataset_uri: str,
    dataset_hash: str,
    git_sha: str,
    kfp_run_id: str,
    triggered_by: str,                # "manual" | "drift" | "scheduled"
    model_version_out: dsl.OutputPath("String"),
    model_uri_out: dsl.OutputPath("String"),
) -> None:
    import json
    import os
    from pathlib import Path

    import mlflow
    from mlflow.tracking import MlflowClient

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    client = MlflowClient()

    metrics_dict = json.loads(Path(metrics).read_text())

    # 같은 dataset_hash + git_sha 가 이미 등록되어 있으면 중복 등록 회피
    existing = client.search_model_versions(
        f"name='{model_name}' and tags.dataset_hash='{dataset_hash}' and tags.git_sha='{git_sha}'"
    )
    if existing:
        v = existing[0]
        print(f"[register] reuse existing version {v.version}")
    else:
        with mlflow.start_run(run_name=f"{model_name}-{kfp_run_id[:8]}") as run:
            mlflow.log_params({"triggered_by": triggered_by})
            mlflow.log_metrics({k: v for k, v in metrics_dict.items() if isinstance(v, (int, float))})
            # 아티팩트 업로드 (TorchScript)
            mlflow.log_artifacts(model_dir, artifact_path="model")
            artifact_uri = f"runs:/{run.info.run_id}/model"
            mv = mlflow.register_model(artifact_uri, model_name)
        v = mv

    # 표준 lineage 태그 부착
    for k, val in {
        "dataset_uri": dataset_uri,
        "dataset_hash": dataset_hash,
        "git_sha": git_sha,
        "kfp_run_id": kfp_run_id,
        "triggered_by": triggered_by,
    }.items():
        client.set_model_version_tag(model_name, v.version, k, val)

    # staging alias 부여
    try:
        client.set_registered_model_alias(model_name, "staging", v.version)
    except Exception as e:
        print(f"[register] alias set warn: {e}")

    # storageUri 는 MinIO 경로 (KServe storageUri 호환 형식).
    # MLflow 가 artifact-root 로 s3://mlflow-artifacts 를 쓰므로 그대로 사용 가능.
    run_id = client.get_model_version(model_name, v.version).run_id
    storage_uri = f"s3://mlflow-artifacts/{run_id.split('/')[0]}/{run_id}/artifacts/model"
    # 단순화를 위해 client.get_run 으로 정확한 artifact_uri 를 추출.
    art = client.get_run(run_id).info.artifact_uri.rstrip("/") + "/model"
    storage_uri = art.replace("mlflow-artifacts:", "s3://mlflow-artifacts").replace("s3:/", "s3://").replace("///", "//")

    Path(model_version_out).write_text(str(v.version))
    Path(model_uri_out).write_text(storage_uri)
    print(f"[register] {model_name} v{v.version} staging alias set. storageUri={storage_uri}")
