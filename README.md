# MLP MLOps 플랫폼

on-prem K8s 위에서 **MinIO + Kubeflow Pipelines + MLflow + KServe(Raw) + Istio + Harbor + Evidently** 를 엮어 만든 MLP MLOps 파이프라인. drift 감지 → 자동 fine-tune → canary 점진 배포 → 자동 롤백 루프를 글루 컨트롤러 한 겹으로 묶었다.

## 디렉토리

| 경로 | 내용 |
|------|------|
| [bootstrap/](bootstrap/)             | RKE2 / MetalLB / Longhorn / Istio / cert-manager / kube-prometheus-stack / Harbor / MinIO / MLflow / KFP / KServe 설치 |
| [pipelines/](pipelines/)             | KFP v2 파이프라인 (`train`, `finetune`) + 재사용 컴포넌트 |
| [serving/](serving/)                 | KServe InferenceService 템플릿 + Istio VirtualService/DestinationRule + Inference Logger |
| [monitoring/](monitoring/)           | Evidently CronJob, PrometheusRule, ServiceMonitor, Grafana 대시보드 |
| [controller/](controller/)           | drift→KFP / canary step-up / 즉시 롤백 글루 (FastAPI webhook + 두 종류의 Job) |
| [images/](images/)                   | 공통 trainer / evidently / webhook / promote / rollback Dockerfile |
| [scripts/](scripts/)                 | `apply-all.sh`, `e2e_smoke.sh`, drift 시뮬레이터 |
| [fixtures/](fixtures/)               | iris 등 smoke 데이터 |
| [docs/](docs/)                       | [새 모델 추가 가이드](docs/adding-a-new-model.md), 핸드오프 문서 |

## 설치 순서

```bash
# 1. 클러스터
sudo bootstrap/cluster/install-rke2.sh server
sudo bootstrap/cluster/post-install.sh

# 2. 플랫폼 컴포넌트
bootstrap/platform/install-phase1.sh
bootstrap/platform/install-phase2.sh

# 3. 이미지 빌드 → Harbor
images/build-and-push.sh

# 4. KFP 파이프라인 컴파일/업로드 + ConfigMap pipeline-ids
pipelines/compile-and-register.sh

# 5. 글루 매니페스트 적용 (RBAC, monitoring, serving, webhook)
scripts/apply-all.sh

# 6. End-to-end smoke
scripts/e2e_smoke.sh all
```

## 자동화 루프 한눈에

```
[KServe payload logger] → s3://inference-logs/
                              │
                              ▼
                  [Evidently CronJob, 15분 주기]
                              │
                       Pushgateway / drift_score
                              │
                              ▼
                  [Prometheus rule MLPDriftHigh]
                       firing > 30분
                              │
                              ▼
            [Alertmanager → ml-webhook /trigger]
                              │  KFP SDK
                              ▼
                  [finetune_pipeline KFP run]
        pull prod ckpt → assemble dataset → train → eval
              register(Staging) → deploy canary 10%
                              │
                              ▼
                  [promote Job — canary step-up]
              10% → 50% → 100% (SLO 통과 시)
                              │
                              ▼
        MLflow alias prod ← new / previous ← old
        stable InferenceService storageUri 갱신

SLO 위반 / Alertmanager critical → ml-webhook /rollback → rollback Job
        → VS weight 100/0 → canary scale-to-zero → Grafana annotation
```

## 핵심 설계 결정

| 결정 | 이유 |
|------|------|
| Argo CD/Rollouts 미사용, kubectl 직접 | 운영 단순화 — 자동화 글루는 한 곳(`controller/`)에만 둠 |
| KServe **Raw Deployment** | Knative 의존성 제거, 표준 K8s Deployment/HPA 만 사용 |
| Istio VirtualService weight 로 canary | KServe canaryTrafficPercent 가 Raw 모드에서 제한적이라 명시적 VS 제어가 더 안정 |
| MLflow alias (`production`/`previous`/`staging`) | stage transition 보다 즉시 재롤백 가능 — alias 하나만 옮기면 됨 |
| Evidently → Pushgateway → Prometheus → Alertmanager | drift 신호와 SLO 신호를 단일 알림 파이프로 통일 |
| 매 배포마다 manifest 스냅샷을 MinIO 에 보관 | "직전 manifest" 가 항상 명확 — 깊은 롤백이 `mc cp` + `kubectl apply` 한 줄 |

자세한 설계 근거는 `~/.claude/plans/ai-model-mlp-async-aurora.md` 참고.
