"""파이프라인 정의에서 공통으로 쓰는 유틸 (컴포넌트 본문에선 import 금지).

KFP v2 에서 컴포넌트 함수는 격리되어 직렬화되므로, 여기 헬퍼는 *파이프라인 함수*
(train_pipeline / finetune_pipeline) 에서만 호출한다.
"""
from __future__ import annotations

from kfp.kubernetes import use_config_map_as_env, use_secret_as_env

TRAINER_IMAGE = "kfp-registry:5000/mlplatform/trainer:latest"

# MLflow 모델 alias 규약: prod 는 항상 'production', 직전 prod 는 'previous'.
ALIAS_PRODUCTION = "production"
ALIAS_PREVIOUS = "previous"
ALIAS_STAGING = "staging"

# k3s 의 ConfigMap / Secret 이름. apply-all.sh 또는 setup-env-resources.sh 가 생성.
ENV_CONFIGMAP = "mlp-endpoints"
ENV_SECRET = "mlp-s3"


def attach_platform_env(task):
    """모든 컴포넌트 task 에 MLflow/MinIO endpoint + S3 자격 주입.

    호출 site 마다 한 줄: `attach_platform_env(my_task(...))`.
    안 쓰는 env 가 주입돼도 무해 — 컴포넌트가 os.environ 으로 명시 참조하는 것만 쓴다.
    """
    use_config_map_as_env(
        task,
        config_map_name=ENV_CONFIGMAP,
        config_map_key_to_env={
            "MLFLOW_TRACKING_URI": "MLFLOW_TRACKING_URI",
            "MINIO_ENDPOINT": "MINIO_ENDPOINT",
            # mlflow client (boto3) 가 S3 artifact 업로드 시 참조 — 없으면 실제 AWS 로 감.
            "MLFLOW_S3_ENDPOINT_URL": "MLFLOW_S3_ENDPOINT_URL",
        },
    )
    use_secret_as_env(
        task,
        secret_name=ENV_SECRET,
        secret_key_to_env={
            "AWS_ACCESS_KEY_ID": "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY": "AWS_SECRET_ACCESS_KEY",
            "MINIO_ACCESS_KEY": "MINIO_ACCESS_KEY",
            "MINIO_SECRET_KEY": "MINIO_SECRET_KEY",
        },
    )
    return task
