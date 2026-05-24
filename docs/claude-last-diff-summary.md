# Claude session — last diff summary

세션 종료 시점 (2026-05-24 16:35 KST) 기준 *실제 변경* 요약. Phase 2 의 glue green-light 까지.

---

## 1. Commit ledger (이 세션들 전체)

| Hash | 한 줄 | 진실 검증 |
|---|---|---|
| `026f8ad` | dead code / deprecated APIs / registry hostname / finetune type bug | compile OK 양쪽 |
| `3c6df20` | docs: handoff snapshot (Phase 1 시작 전) | — |
| `23bf842` | feat: inject env via kfp-kubernetes (`attach_platform_env`) | yaml 의 `platforms.kubernetes` 에 spec |
| `54f66e0` | trainer requirements 에서 kfp 제거 → kubernetes==30 호환 | docker build OK |
| `7bf308c` | chore(gitignore): 컴파일 산출물 + iris.csv | — |
| `d5da6ac` | preprocess: np.savez_compressed 의 .npz auto-suffix → file handle | run-2 의 train+evaluate 통과 |
| `247a9bb` | env: MLFLOW_S3_ENDPOINT_URL → mlflow client 가 Pi4 MinIO 가리킴 | run-3 register 통과, mlp v1 |
| `f436289` | docs: phase 1 green-light snapshot | — |
| `ad89b13` | scripts/compile-and-register idempotent + venv-aware rewrite | mlp-train/mlp-finetune 새 version 추가 |
| `e789c39` | trainer image diet: CUDA → CPU base, 8.66GB → 1.81GB (5×↓) | run-4 동일 green-light, mlp v2 |
| `a3c3987` | docs: snapshot before Phase 2 | — |
| `6fb5b34` | claude permission allowlist + deny (32 allow + 19 deny) | — |
| `3f057ca` | trainer: jinja templates baked + deploy_canary base_name fix | image 안에 /templates/ 두 파일, run-5 진전 |
| `b12cbbd` | trainer: kubectl v1.29.0 baked (+50MB → 1.86GB) | run-6 의 deploy_canary 가 CRD 부재까지 도달 |

---

## 2. Out-of-tree state (현재)

### Pi4 (192.168.1.37)
- 컨테이너: `minio`, `registry`, `mlflow` 모두 Up
- 버킷: `mlflow-artifacts`, `datasets`, **`serving-manifests`** (Phase 2 추가), `tmp`
- model artifact (v1, v2): MinIO 의 `mlflow-artifacts/0/<run_uuid>/artifacts/model/{model.pt, state_dict.pt, meta.json}`
- serving manifest snapshot (run-7): `serving-manifests/mlp/20260524T073016Z/{canary-isvc.yaml, virtualservice.yaml}`

### leaf007 (k3s control + compute)
- 시스템 설정 (sudo 1회): `/etc/hosts`, `/etc/rancher/k3s/registries.yaml`, `/etc/docker/daemon.json` insecure-registries
- SSH key `~/.ssh/id_ed25519` GitHub + 라파 둘 다 등록
- venv `.venv/` (kfp 2.16.1, kfp-kubernetes, mlflow, pandas, scikit-learn 등)
- Docker images: `kfp-registry:5000/mlplatform/trainer:b12cbbd`, `:3f057ca`, `:6fb5b34`, `:cpu-tpl`, `:cpu`, `:latest` (모두 1.81~1.86GB)
- Disk 78%

### k3s 리소스
- **kubeflow ns**: KFP pods (ml-pipeline, mysql, seaweedfs), `mlp-endpoints` ConfigMap, `mlp-s3` Secret, `kfp-pipeline-runner` SA + `pipeline-env` Secret + `serving-templates` ConfigMap
- **mlops ns**: `pipeline-ids` ConfigMap
- **cert-manager ns**: cert-manager + cainjector + webhook (3 pod)
- **istio-system ns**: istiod + istio-ingressgateway (EXTERNAL-IP=192.168.1.154) + `kserve-gateway` Gateway
- **kserve ns**: kserve-controller-manager (2/2 Running, kube-rbac-proxy=quay.io/brancz/kube-rbac-proxy:v0.14.0 patched), 10 ClusterServingRuntime
- **serving ns**: `kserve-s3` SA + `minio-s3-creds` Secret (Pi4 자격), `kfp-serving-deployer` Role + 2 RoleBindings, `mlp-canary` InferenceService + `mlp` VirtualService

---

## 3. Phase 1 + Phase 2 의 진실

### Phase 1 — 학습 → MLflow 등록
- mlp v1 (run-3, smoke-mlflow-s3-fix) + v2 (run-4, smoke-cpu-image)
- 둘 다 5종 lineage 태그 miss=OK, staging alias=v2

### Phase 2 — KServe 통합 (glue)
- **run-7 (b1632e43) 전체 KFP pipeline SUCCEEDED**
- deploy_canary 가 진짜 InferenceService + VirtualService 생성
- MinIO `serving-manifests/` 에 yaml snapshot 적재
- KServe storage-initializer 가 Pi4 MinIO 에서 model artifact pull 성공

### 남은 자리 — 모델 packaging
- torchserve runtime 이 `.mar` archive + `config.properties` 기대
- 우리 artifact 는 raw state_dict + scripted .pt → predictor pod CrashLoopBackOff
- handoff §8.B.1 (torch-model-archiver 추가) 가 다음 첫 작업

---

## 4. 자원 상태

| | RAM 가용 | Disk 가용 | 주요 컴포넌트 |
|---|---|---|---|
| leaf007 (16 GB) | ~9 GB | ~30 GB (78%) | k3s + KFP + cert-manager + Istio + KServe |
| Pi4 (8 GB) | ~6.5 GB | 외장 SSD 233GB 여유 | MinIO + MLflow + registry |

Phase 2 의 cluster install 후 leaf007 RAM 사용량이 약 2GB 증가 (cert-manager 130MB + istiod 300MB + ingressgateway 150MB + KServe controller 200MB + InferenceService predictor 2x ~1.5GB).

---

## 5. 다음 세션 첫 액션

`docs/ai-handoff.md §7` wake-up → `§8.B.1` (`.mar` archive 생성). 또는 §8.B.3 (Phase 3 으로 직진, serving 호출은 별도).

```bash
cd /home/fall/dev/ai_platform
source .venv/bin/activate
kubectl get nodes && kubectl -n serving get isvc,vs,pods
ssh fall@192.168.1.37 'docker ps --format "table {{.Names}}\t{{.Status}}"'
# port-forward 재기동
kubectl -n kubeflow port-forward svc/ml-pipeline 8888:8888 >/tmp/kfp-pf.log 2>&1 &
```

---

## 6. 이 세션이 *안* 한 것

- 모델 packaging (`.mar`) — predictor pod 의 진짜 Ready 까지는 별도 sub-step
- `mlp v2` 를 production alias 로 이동 — 지금 staging. finetune_pipeline 의 dry-run 위해서 production 필요
- Phase 3 (Prometheus + Evidently + ml-webhook + drift 자동 finetune)
- `evidently-job`, `ml-webhook`, `promote/rollback` Job 이미지 빌드
- `pipelines/finetune_pipeline` 의 실제 run 검증 (compile 만)
- AGENTS.md commit (사용자가 추가한 Codex 진입, untracked 유지)

---

## 7. 다음 세션의 *예상 첫 진전 신호*

`.mar` archive 생성 후 train_pipeline 재실행:
- preprocess → train_mlp 이 `.mar` 도 같이 산출
- register_to_mlflow 가 `.mar` 도 artifact 에 포함
- deploy_canary 가 InferenceService 생성 (이미 동작)
- predictor pod 의 `storage-initializer` 가 새 artifact pull
- **`kserve-container` (torchserve) 가 `mlp.mar` 인식 → Ready**
- `curl mlp.mlplatform.local/v1/models/mlp:predict` 가 200 + 정상 prediction

이게 *Phase 2 의 완전한 green-light*.
