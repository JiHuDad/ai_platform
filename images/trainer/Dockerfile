# 공통 trainer 베이스 이미지 (CPU-only).
# 모든 KFP 컴포넌트가 이걸 base 로 쓴다. iris/MLP 학습은 CUDA 불필요 — slim + cpu torch.
FROM python:3.10-slim

ARG TARGETARCH=amd64

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://dl.min.io/client/mc/release/linux-${TARGETARCH}/mc" -o /usr/local/bin/mc \
    && chmod +x /usr/local/bin/mc

WORKDIR /app
COPY requirements.txt /app/requirements.txt
# torch 만 CPU index 에서 받음 (CUDA wheel ~700MB 대신 CPU wheel ~200MB).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.3.0 \
    && pip install --no-cache-dir -r /app/requirements.txt

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
