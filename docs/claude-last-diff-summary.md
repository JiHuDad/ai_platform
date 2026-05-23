# Claude session — last diff summary

세션 종료 시점 기준의 *실제 변경* 요약. 카파시 톤: 무엇이 *진짜로* 바뀌었는지만.

---

## 1. Repo diff

```
docs/ai-handoff.md            | +302 (new)
docs/claude-last-diff-summary.md | +<this file>
```

**소스 코드 변경 없음.** `pipelines/`, `controller/`, `monitoring/`, `serving/`, `bootstrap/`, `scripts/`, `images/`, `fixtures/` 모두 무손상. 마지막 코드 커밋은 `a28091e docs: add CLAUDE.md`.

---

## 2. Out-of-tree changes (Pi4 @ 192.168.1.37)

저장소 밖에서 일어난 변경. 인계받는 에이전트가 *이 상태를 가정* 해도 됨.

### Containers
| 이름 | 상태 변화 | 이미지 | 포트 |
|---|---|---|---|
| `minio` | 변경 없음 (10일 가동중) | `quay.io/minio/minio:latest` | 9000, 9001 |
| `registry` | 변경 없음 (10일 가동중) | `registry:2` | 5000 |
| `mlflow` | **신규** | `ghcr.io/mlflow/mlflow:v2.16.2` | 5001 → 5000 |

### Filesystem
- `/mnt/data/mlflow/` 신규 디렉토리 (MLflow SQLite backend store)
- `/mnt/data/minio/mlflow-artifacts/` 신규 (빈 버킷)
- `/mnt/data/minio/datasets/` 신규 (빈 버킷)

### SSH
- `leaf007:/home/fall/.ssh/id_ed25519{,.pub}` 신규 (key comment: `leaf007-fall@20260523`)
- 라파의 `~fall/.ssh/authorized_keys` 에 위 공개키 추가됨 — 사용자가 외부 셸에서 수동 등록

---

## 3. Decisions (분석 → 합의된 것)

1. **README 의 RKE2/Harbor 풀스택 비사용.** k3s 47일 안정 가동 + 기존 인프라 활용이 정직.
2. **Pi4 (8GB) 가 control-plane.** leaf007 의 16GB 메모리 압박이 *물리적으로 증명* 된 경우의 분리.
3. **MLflow port 5001.** registry:2 가 5000 점유. 기존 컨테이너 안 건드림.
4. **KFP 내장 seaweedfs 미사용.** lineage 진리원본을 Pi4 MinIO 하나로 통일.
5. **Phase 분할: 1 = train→MLflow 까지, 2 = serving, 3 = 자동화 루프.** 한 번에 다 안 건드림.

---

## 4. Pending bugs (commit 안 됨)

Phase 1 step 6 에서 일괄 fix 예정. 자세한 위치/수정안은 `ai-handoff.md §6`.

- `controller/webhook/main.py:70` — dead code `if False`
- `controller/canary-job/promote.py:141` — `dir()` 로 로컬 변수 체크
- `monitoring/evidently-job/run.py:87` — pandas `fillna(method="ffill")` deprecated
- `pipelines/finetune_pipeline.py` — base_dataset_uri lineage 누락
- `harbor.mlplatform.local` hardcode (15개+ 파일) → `kfp-registry:5000` 으로 일괄 sed 필요

---

## 5. Next pending action

`docs/ai-handoff.md §8 Step 6` — Quick fix + endpoint sed 한 commit. 그 commit 이 들어가면 step 7 (trainer image build) 으로 진행.

검증 명령:
```bash
git grep harbor.mlplatform.local                       # 0 lines
python -c "from pipelines.train_pipeline import train_pipeline; \
           from kfp.compiler import Compiler; \
           Compiler().compile(train_pipeline, '/tmp/t.yaml'); \
           print('compile OK')"
```

이 둘이 통과하면 step 6 종료.

---

## 6. What this session did *not* do

- 어떤 KFP run 도 제출 안 함
- 어떤 컨테이너 이미지도 빌드 안 함
- 어떤 모델도 학습 안 함
- 어떤 코드 파일도 수정 안 함

이 세션은 **진단 + 환경구성 + 인계 문서화** 만. Phase 1 의 코드 작업은 다음 세션의 일.
