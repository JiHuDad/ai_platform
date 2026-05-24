# 공통 trainer 베이스 이미지 (CPU-only).
# 모든 KFP 컴포넌트가 이걸 base 로 쓴다. iris/MLP 학습은 CUDA 불필요 — slim + cpu torch.
#
# Build context: repo root (deploy_canary 가 /templates/ 의 jinja 파일을 읽으므로
#   serving/ 디렉토리도 image 안에 함께 넣어야 한다).
# 따라서 빌드 명령은: docker build -f images/trainer/Dockerfile -t <tag> .
FROM python:3.10-slim

ARG TARGETARCH=amd64

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://dl.min.io/client/mc/release/linux-${TARGETARCH}/mc" -o /usr/local/bin/mc \
    && chmod +x /usr/local/bin/mc \
    && curl -fsSL "https://dl.k8s.io/release/v1.29.0/bin/linux/${TARGETARCH}/kubectl" -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl

WORKDIR /app
COPY images/trainer/requirements.txt /app/requirements.txt
# torch 만 CPU index 에서 받음 (CUDA wheel ~700MB 대신 CPU wheel ~200MB).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.3.0 \
    && pip install --no-cache-dir -r /app/requirements.txt

# Jinja templates 가 deploy_canary 컴포넌트 본문에서 /templates/ 경로로 로딩된다.
COPY serving/inferenceservice/mlp.yaml.j2     /templates/inferenceservice.yaml.j2
COPY serving/istio/virtualservice.yaml.j2     /templates/virtualservice.yaml.j2

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
