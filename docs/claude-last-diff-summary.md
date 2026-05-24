# Claude session — last diff summary

세션 종료 시점 (2026-05-24 11:50 KST) 기준 *실제 변경* 요약.

---

## 1. Commit ledger (이 세션들 전체)

| Hash | 한 줄 | 진실 검증 |
|---|---|---|
| `026f8ad` | dead code / deprecated APIs / registry hostname / finetune type bug | compile OK 양쪽 |
| `3c6df20` | docs: handoff snapshot (Phase 1 시작 전) | — |
| `23bf842` | feat: inject env via kfp-kubernetes (`attach_platform_env`) | yaml 의 `platforms.kubernetes` 에 spec |
| `54f66e0` | trainer requirements 에서 kfp 제거 → kubernetes==30 호환 | docker build OK, 8.66GB |
| `7bf308c` | chore(gitignore): 컴파일 산출물 + iris.csv | — |
| `d5da6ac` | preprocess: np.savez_compressed 의 .npz auto-suffix → file handle | run-2 의 train + evaluate 통과 |
| `247a9bb` | env: MLFLOW_S3_ENDPOINT_URL → mlflow client 가 Pi4 MinIO 가리킴 | run-3 register 통과, mlp v1 등록 |
| `f436289` | docs: phase 1 green-light snapshot | — |
| `ad89b13` | scripts/compile-and-register idempotent + venv-aware rewrite | 한 호출 → mlp-train/mlp-finetune 새 version 추가 + ConfigMap 갱신 |
| `e789c39` | trainer image diet: CUDA → CPU base, 8.66GB → 1.81GB (5×↓) | run-4 동일 green-light, mlp v2 등록 |

---

## 2. Out-of-tree state (현재)

### Pi4 (192.168.1.37)
- 컨테이너: `minio` (11d), `registry` (11d), `mlflow` (1d) 모두 Up
- 버킷: `mlflow-artifacts` (v1+v2 의 model artifact), `datasets` (iris.csv), `tmp` (잔재)
- 외장 SSD `/mnt/data` ext4 거의 빈 상태

### leaf007 (k3s control + compute)
- 시스템 설정 (sudo, 1회): `/etc/hosts` 의 `127.0.0.1 kfp-registry`, `/etc/rancher/k3s/registries.yaml`, `/etc/docker/daemon.json` 의 insecure-registries
- SSH key `~/.ssh/id_ed25519` 라파에 등록됨
- venv `/home/fall/dev/ai_platform/.venv/` (Python 3.12, kfp 2.16.1, kfp-kubernetes, mlflow, pandas, scikit-learn)
- Docker image: `kfp-registry:5000/mlplatform/trainer:cpu` / `:latest` (**1.81 GB**, 이전 8.66 GB image 는 prune 됨)
- Disk 78% (이전 86% → 정리 1.78 GB)

### k3s 리소스
- `kubeflow/mlp-endpoints` ConfigMap — `MLFLOW_TRACKING_URI`, `MINIO_ENDPOINT`, `MLFLOW_S3_ENDPOINT_URL`
- `kubeflow/mlp-s3` Secret — `AWS_*` + `MINIO_*` 자격 4개
- `mlops/pipeline-ids` ConfigMap — train + finetune pipeline ID
- KFP 의 `mlp-train` (3732a01c, 여러 version), `mlp-finetune` (68d663f3, 여러 version)
- `smoke` Experiment + 4 runs (`train-smoke-1/2/3/4-cpu`)

### MLflow 등록 (Phase 1 의 진실)
- `mlp` v1 + v2 — staging alias = v2. 5종 lineage 태그 둘 다 채움.

---

## 3. 자원 상태 (지금)

| | RAM 가용 | Disk 가용 |
|---|---|---|
| leaf007 (16 GB) | **11 GB** | 30 GB (78%) |
| Pi4 (8 GB) | **6.5 GB** | 외장 SSD 233 GB 거의 비어있음 |

Phase 2 어림 (cert-manager + Istio + KServe + 1개 InferenceService): RAM ~2.2 GB, Disk ~3 GB → leaf007 단독으로 충분.

---

## 4. 다음 세션 첫 액션

`docs/ai-handoff.md §7` 의 wake-up 5분 → `§8.A.1` (trainer image 에 templates COPY) 부터 시작.

```bash
cd /home/fall/dev/ai_platform
source .venv/bin/activate
kubectl get nodes
ssh fall@192.168.1.37 'docker ps --format "table {{.Names}}\t{{.Status}}"'
# port-forward 살아있을 가능성 — 아니면 재기동:
kubectl -n kubeflow port-forward svc/ml-pipeline 8888:8888 >/tmp/kfp-pf.log 2>&1 &
```

---

## 5. 이 세션이 *안* 한 것

- Phase 2 (cert-manager / Istio / KServe 설치) 손도 안 댐 — *명시적으로 다음 세션의 시작점*.
- `finetune_pipeline` 의 실제 run 검증 — compile 만 통과. `production` alias 가 없어 dry-run 도 사실상 못 함. Phase 2 끝나면 v2 → production 옮긴 후 가능.
- `evidently-job`, `ml-webhook`, `promote/rollback` Job 이미지 빌드 — Phase 3 영역.
- AGENTS.md (사용자가 추가한 Codex 진입 문서) — untracked 그대로 둠.

다음 세션은 위 항목 중 *진짜 다음에 필요한 것* 만 골라잡으면 된다.
