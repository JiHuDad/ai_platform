"""Evidently drift 검사 작업.

흐름:
  1. MinIO 의 `s3://reference-data/<model>/<version>/reference.parquet` 로딩.
  2. `s3://inference-logs/<model>/<날짜윈도>/...jsonl` 최근 N 분치 로딩.
  3. Evidently DataDriftPreset 으로 리포트 → drift_score 계산.
  4. Prometheus Pushgateway 로 `mlp_drift_score`, `mlp_feature_drift_count` push.
  5. HTML 리포트는 `s3://drift-reports/<model>/<ts>.html` 로 업로드.

Pod 환경변수:
  MODEL_NAME, MODEL_VERSION, WINDOW_MINUTES, MINIO_ENDPOINT, AWS_* , PUSHGATEWAY_URL
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import boto3
import pandas as pd
from evidently.metric_preset import DataDriftPreset
from evidently.report import Report
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

log = logging.getLogger("evidently-job")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def s3():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )


def load_reference(model_name: str, model_version: str) -> pd.DataFrame:
    obj = s3().get_object(
        Bucket="reference-data",
        Key=f"{model_name}/{model_version}/reference.parquet",
    )
    return pd.read_parquet(io.BytesIO(obj["Body"].read()))


def load_recent_logs(model_name: str, window_minutes: int) -> pd.DataFrame:
    c = s3()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    rows: list[dict] = []
    paginator = c.get_paginator("list_objects_v2")
    # canary + stable 모두 수집
    for variant in ("stable", "canary"):
        prefix = f"{model_name}/{variant}/"
        for page in paginator.paginate(Bucket="inference-logs", Prefix=prefix):
            for it in page.get("Contents", []):
                if it["LastModified"] < cutoff:
                    continue
                body = c.get_object(Bucket="inference-logs", Key=it["Key"])["Body"].read()
                for line in body.splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    feats = rec.get("instances") or rec.get("inputs") or []
                    for inst in feats:
                        if isinstance(inst, list):
                            rows.append({f"f{i}": v for i, v in enumerate(inst)})
                        elif isinstance(inst, dict):
                            rows.append(inst)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def compute_drift(reference: pd.DataFrame, current: pd.DataFrame) -> tuple[float, int, str]:
    """drift_score (0~1), feature_drift_count, html report"""
    feature_cols = [c for c in reference.columns if c != "label"]
    ref = reference[feature_cols]
    cur = current[[c for c in feature_cols if c in current.columns]]
    # 컬럼 정렬 일치화
    cur = cur.reindex(columns=feature_cols).ffill().fillna(0.0)

    report = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=ref, current_data=cur)
    j = report.as_dict()
    metrics = j["metrics"][0]["result"]
    drift_score = float(metrics.get("dataset_drift", False))   # bool → 0/1
    feature_drift_count = int(metrics.get("number_of_drifted_columns", 0))
    share_drifted = float(metrics.get("share_of_drifted_columns", 0.0))
    return share_drifted, feature_drift_count, report.get_html()


def push_metrics(model: str, drift_share: float, drift_count: int):
    reg = CollectorRegistry()
    g1 = Gauge("mlp_drift_score", "Share of drifted features", ["model"], registry=reg)
    g2 = Gauge("mlp_feature_drift_count", "Number of drifted features", ["model"], registry=reg)
    g1.labels(model=model).set(drift_share)
    g2.labels(model=model).set(drift_count)
    push_to_gateway(os.environ["PUSHGATEWAY_URL"], job=f"evidently-{model}", registry=reg)


def upload_report(model: str, html: str) -> str:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    key = f"{model}/{ts}.html"
    s3().put_object(Bucket="drift-reports", Key=key, Body=html.encode(), ContentType="text/html")
    return f"s3://drift-reports/{key}"


def main():
    model = os.environ["MODEL_NAME"]
    version = os.environ["MODEL_VERSION"]
    window = int(os.environ.get("WINDOW_MINUTES", "60"))

    log.info("loading reference: %s v%s", model, version)
    ref = load_reference(model, version)

    log.info("loading inference logs (last %d min)", window)
    cur = load_recent_logs(model, window)
    if cur.empty:
        log.warning("no inference logs in window — skipping drift")
        push_metrics(model, 0.0, 0)
        return 0

    log.info("running Evidently report (n_ref=%d n_cur=%d)", len(ref), len(cur))
    drift_share, drift_count, html = compute_drift(ref, cur)
    log.info("drift_share=%.3f feature_drift_count=%d", drift_share, drift_count)

    push_metrics(model, drift_share, drift_count)
    uri = upload_report(model, html)
    log.info("report → %s", uri)
    return 0


if __name__ == "__main__":
    sys.exit(main())
