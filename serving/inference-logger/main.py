from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, Request

app = FastAPI()


def s3():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["MINIO_ENDPOINT"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )


def rows_from_payload(payload) -> list:
    if isinstance(payload, dict):
        if "instances" in payload:
            return rows_from_payload(payload["instances"])
        if "inputs" in payload:
            inputs = payload["inputs"]
            if inputs and isinstance(inputs[0], dict) and "data" in inputs[0]:
                return rows_from_payload(inputs[0]["data"])
            return rows_from_payload(inputs)
        for key in ("request", "raw", "body", "data"):
            if key in payload:
                return rows_from_payload(payload[key])
    if isinstance(payload, list):
        return payload
    return []


def ensure_bucket(c, bucket: str):
    try:
        c.head_bucket(Bucket=bucket)
    except ClientError:
        c.create_bucket(Bucket=bucket)


@app.post("/log/{model}/{variant}")
async def log_payload(model: str, variant: str, request: Request):
    raw = await request.body()
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {"body": raw.decode(errors="replace")}

    now = datetime.now(timezone.utc)
    record = {
        "ts": now.isoformat(),
        "model": model,
        "variant": variant,
        "raw": payload,
    }
    rows = rows_from_payload(payload)
    if rows:
        record["instances"] = rows

    bucket = os.environ.get("SINK_BUCKET", "inference-logs")
    key = f"{model}/{variant}/{now:%Y%m%d}/{now:%H%M%S}-{uuid.uuid4().hex}.jsonl"
    body = (json.dumps(record, separators=(",", ":")) + "\n").encode()

    c = s3()
    ensure_bucket(c, bucket)
    c.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/x-ndjson")
    return {"ok": True, "key": key, "rows": len(rows)}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
