#!/usr/bin/env bash
# 로컬 registry 로 이미지 빌드/푸시. 이미지 태그는 git short SHA.
set -euo pipefail

REGISTRY="${REGISTRY:-kfp-registry:5000/mlplatform}"
TAG="${TAG:-$(git -C "$(dirname "$0")/.." rev-parse --short HEAD 2>/dev/null || date +%s)}"

cd "$(dirname "$0")"

images=(
  "trainer"
  "transformer"
  "evidently-job"
  "ml-webhook"
)

for img in "${images[@]}"; do
  if [[ ! -f "${img}/Dockerfile" && ! -f "../monitoring/${img}/Dockerfile" && ! -f "../controller/${img}/Dockerfile" ]]; then
    continue
  fi
  if [[ -f "${img}/Dockerfile" ]]; then        ctx="${img}";             fi
  if [[ -f "../monitoring/${img}/Dockerfile" ]]; then ctx="../monitoring/${img}"; fi
  if [[ -f "../controller/${img}/Dockerfile" ]]; then ctx="../controller/${img}"; fi

  echo "== build ${img}:${TAG} (ctx=${ctx})"
  docker build -t "${REGISTRY}/${img}:${TAG}" -t "${REGISTRY}/${img}:latest" "${ctx}"
  docker push "${REGISTRY}/${img}:${TAG}"
  docker push "${REGISTRY}/${img}:latest"
done

echo "[ok] tag=${TAG} pushed to ${REGISTRY}"
