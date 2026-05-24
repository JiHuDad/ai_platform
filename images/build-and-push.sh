#!/usr/bin/env bash
# 로컬 registry 로 이미지 빌드/푸시. 이미지 태그는 git short SHA.
# Build context 는 *repo root* (trainer Dockerfile 이 serving/ 의 jinja 파일도 COPY 하기 때문).
set -euo pipefail

REGISTRY="${REGISTRY:-kfp-registry:5000/mlplatform}"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%s)}"

# 항상 repo root 에서 빌드.
cd "$(dirname "$0")/.."

# image_name : dockerfile_path (모두 repo root 기준)
declare -A images=(
  [trainer]="images/trainer/Dockerfile"
  [evidently-job]="monitoring/evidently-job/Dockerfile"
  [ml-webhook]="controller/webhook/Dockerfile"
  [rollback-job]="controller/rollback-job/Dockerfile"
  [canary-job]="controller/canary-job/Dockerfile"
)

for img in "${!images[@]}"; do
  df="${images[$img]}"
  [[ -f "$df" ]] || { echo "[skip] $img — $df 없음"; continue; }

  echo "== build ${img}:${TAG}  (dockerfile=${df})"
  docker build -f "${df}" \
    -t "${REGISTRY}/${img}:${TAG}" \
    -t "${REGISTRY}/${img}:latest" \
    .
  docker push "${REGISTRY}/${img}:${TAG}"
  docker push "${REGISTRY}/${img}:latest"
done

echo "[ok] tag=${TAG} pushed to ${REGISTRY}"
