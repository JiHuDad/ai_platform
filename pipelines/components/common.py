"""파이프라인 컴포넌트에서 공통으로 쓰는 유틸.

KFP v2 에서는 컴포넌트 함수가 격리 환경에서 직렬화되므로,
이 모듈은 *내부* 임포트용이고 컴포넌트 본문은 함수 안에서 다시 import 한다.
"""
from __future__ import annotations

TRAINER_IMAGE = "kfp-registry:5000/mlplatform/trainer:latest"

MLFLOW_TRACKING_URI = "http://mlflow.mlflow.svc.cluster.local:5000"
MINIO_ENDPOINT = "http://minio.minio.svc.cluster.local:9000"

# MLflow 모델 alias 규약: prod 는 항상 'production', 직전 prod 는 'previous'.
ALIAS_PRODUCTION = "production"
ALIAS_PREVIOUS = "previous"
ALIAS_STAGING = "staging"
