# 공통 trainer 베이스 이미지.
# 모든 KFP 컴포넌트와 fine-tune Job 이 이 이미지를 사용한다.
FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

ARG TARGETARCH=amd64

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL "https://dl.min.io/client/mc/release/linux-${TARGETARCH}/mc" -o /usr/local/bin/mc \
    && chmod +x /usr/local/bin/mc

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 파이프라인 컴포넌트 코드가 마운트되어 실행됨 (KFP 가 component spec 으로 주입).
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
