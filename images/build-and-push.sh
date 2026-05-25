#!/usr/bin/env bash
# 로컬 registry 로 이미지 빌드/푸시. 이미지 태그는 git short SHA.
#
# Image 별 build context 가 다르다:
#   - trainer 는 repo root (serving/ 의 jinja 파일 COPY 위해)
#   - 나머지는 각 component 디렉토리 (그 디렉토리의 requirements.txt 만 사용)
set -euo pipefail

REGISTRY="${REGISTRY:-kfp-registry:5000/mlplatform}"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%s)}"

cd "$(dirname "$0")/.."

# image_name : "dockerfile_path|context_path" (둘 다 repo root 기준)
declare -A images=(
  [trainer]="images/trainer/Dockerfile|."
  [evidently-job]="monitoring/evidently-job/Dockerfile|monitoring/evidently-job"
  [ml-webhook]="controller/webhook/Dockerfile|controller/webhook"
  [rollback-job]="controller/rollback-job/Dockerfile|controller/rollback-job"
  [canary-job]="controller/canary-job/Dockerfile|controller/canary-job"
)

for img in "${!images[@]}"; do
  spec="${images[$img]}"
  df="${spec%%|*}"
  ctx="${spec##*|}"
  [[ -f "$df" ]] || { echo "[skip] $img — $df 없음"; continue; }

  echo "== build ${img}:${TAG}  (dockerfile=${df}  context=${ctx})"
  docker build -f "${df}" \
    -t "${REGISTRY}/${img}:${TAG}" \
    -t "${REGISTRY}/${img}:latest" \
    "${ctx}"
  docker push "${REGISTRY}/${img}:${TAG}"
  docker push "${REGISTRY}/${img}:latest"
done

echo "[ok] tag=${TAG} pushed to ${REGISTRY}"
