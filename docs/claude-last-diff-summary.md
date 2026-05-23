# Claude session — last diff summary

세션 종료 시점 (2026-05-23 22:30 KST) 기준 *실제 변경* 요약.

---

## 1. Repo diff (이번 세션 전체)

```
.gitignore                                    | +13  (new)
controller/canary-job/promote.py              |   ~3
controller/webhook/deploy.yaml                |   ~2
controller/webhook/main.py                    |   -3
images/build-and-push.sh                      |   ~2
images/trainer/requirements.txt               |   -1 +3
monitoring/evidently-job/cronjob.yaml         |   ~1
monitoring/evidently-job/run.py               |   ~1
pipelines/components/assemble_finetune_dataset.py | ~1
pipelines/components/common.py                |  +38 -4
pipelines/components/data_ingest.py           |   ~1
pipelines/components/deploy_canary.py         |   ~1
pipelines/components/evaluate.py              |   ~1
pipelines/components/preprocess.py            |  +4 -1
pipelines/components/pull_production_model.py |  rewrite (NamedTuple)
pipelines/components/register_to_mlflow.py    |  +14 -7
pipelines/components/train_mlp.py             |   ~1
pipelines/components/trigger_promote_job.py   |   ~1
pipelines/finetune_pipeline.py                |  +15 -13
pipelines/train_pipeline.py                   |  +14 -12
serving/inference-logger.yaml                 |   ~1
docs/ai-handoff.md                            | rewrite (Phase 1 done)
docs/claude-last-diff-summary.md              | rewrite (이 파일)
```

마지막 commit: `247a9bb fix(env): inject MLFLOW_S3_ENDPOINT_URL ...`

---

## 2. Commit ledger

| Hash | 한 줄 | 검증 |
|---|---|---|
| `026f8ad` | dead code / deprecated APIs / registry hostname / finetune type bug | compile OK 양쪽 |
| `3c6df20` | docs: handoff snapshot (Phase 1 시작 전) | — |
| `23bf842` | feat: inject env via kfp-kubernetes (`attach_platform_env`) | yaml 의 `platforms.kubernetes` 에 spec 적재 확인 |
| `54f66e0` | trainer requirements 에서 kfp 제거 → kubernetes==30 호환 | docker build → push 통과, 8.66GB |
| `7bf308c` | chore(gitignore): 컴파일 산출물 + iris.csv | — |
| `d5da6ac` | preprocess: np.savez_compressed 의 .npz auto-suffix → file handle | run-2 의 preprocess + train_mlp + evaluate Completed |
| `247a9bb` | env: MLFLOW_S3_ENDPOINT_URL → mlflow client 가 Pi4 MinIO 가리킴 | run-3 의 register_to_mlflow 통과, MLflow v1 + 5종 태그, MinIO artifact |

---

## 3. Out-of-tree changes (지속적)

### Pi4 @ 192.168.1.37
- `/mnt/data/mlflow/` 디렉토리 신규 (SQLite backend store)
- 컨테이너 `mlflow` 신규 (`ghcr.io/mlflow/mlflow:v2.16.2`, :5001 → 5000)
- 버킷 `mlflow-artifacts`, `datasets` 신규
- (기존: `minio`, `registry` 컨테이너 + `tmp/` 빈 버킷 — 변경 없음)

### leaf007 (k3s host)
- `/etc/hosts`: `127.0.0.1 kfp-registry` 추가 (sudo, 1회)
- `/etc/rancher/k3s/registries.yaml`: `kfp-registry:5000` insecure mirror (sudo, 1회)
- `/etc/docker/daemon.json`: `insecure-registries: ["kfp-registry:5000"]` (sudo, 1회)
- ed25519 SSH key 신규 (`~/.ssh/id_ed25519`), 라파의 authorized_keys 에 등록됨
- 프로젝트 venv `/home/fall/dev/ai_platform/.venv/` (Python 3.12, kfp 2.16.1, kfp-kubernetes, mlflow, pandas, scikit-learn — 컴파일/제출/검증용)
- Docker image `kfp-registry:5000/mlplatform/trainer:3c6df20` + `:latest` (8.66GB)

### k3s 리소스
- `kubeflow/mlp-endpoints` ConfigMap (3 키)
- `kubeflow/mlp-s3` Secret (4 키)
- `mlops/pipeline-ids` ConfigMap (train + finetune ID)
- KFP 의 `mlp-train` (3732a01c) + `mlp-finetune` (68d663f3) 파이프라인 등록
- `mlops` namespace 신규
- KFP 의 `smoke` Experiment (2bb1effe) + 3개 run (`train-smoke-1/2/3`)

---

## 4. Phase 1 진실 (그린라이트)

`mlp v1` MLflow 에 등록, 5종 lineage 태그 전부 채워짐, MinIO 에 model artifact 적재. `docs/ai-handoff.md §4` 에 raw 출력 박혀있음.

---

## 5. 다음 세션 첫 액션

`docs/ai-handoff.md §7` 의 wake-up 명령 → `§8` 의 작업 후보. 추천 시작점:

```bash
cd /home/fall/dev/ai_platform
source .venv/bin/activate
kubectl get nodes && ssh fall@192.168.1.37 'docker ps --format "table {{.Names}}\t{{.Status}}"'
```

위 둘 다 그린 → `§8.B` (Phase 1 정리) 또는 `§8.A` (Phase 2 시작) 선택.

---

## 6. 이 세션이 *안* 한 것

- Phase 2 (serving stack — Istio/KServe/cert-manager) 손도 안 댐.
- `pipelines/compile-and-register.sh` 의 path/venv 버그 정리 안 함 — 인라인 명령으로 우회 중.
- `MLflow` 의 `staging` alias 가 실제로 적용됐는지 확인 안 함 — register 로그는 set 했다고 print, search API 는 `aliases=[]` (API limitation 의심).
- `finetune_pipeline` 의 실제 run 검증 — compile 만 통과한 상태.
- `evidently-job`, `ml-webhook`, `promote/rollback` Job 이미지 빌드 안 함 — Phase 3 영역.

다음 세션이 들어왔을 때 이 6개 중 *진짜 다음에 필요한 것* 만 골라잡는 게 정직.
