# 프로젝트 작업 가이드 — Karpathy 스타일

이 저장소의 모든 작업은 **Andrej Karpathy 스타일**로 진행한다. 어시스턴트는 새 작업을 시작하기 전 이 파일을 한 번 훑고, 코드/문서를 쓸 때마다 아래 원칙으로 자기 검열한다.

> "I want code that's so simple I can hold the whole thing in my head."

## 핵심 원칙

1. **From scratch, hackable.** 프레임워크에 숨지 말고 밑바닥에서부터 직접 짠다. `nanoGPT` / `micrograd` 처럼 단일 파일에 가까운 형태가 이상적. 추상화는 *증명된 중복* 다음에만 만든다. Helm template 의 `{{ if }}` 가 두 단 이상이면 그건 이미 졌다.

2. **Simple is better. 10× simpler if possible.** "이거 하나 빼도 되나?"를 매 PR 마다 5번 묻는다. 옵션, 플래그, 설정 항목, 헬퍼 함수, dispatch — 전부 의심한다. *합쳐도 되는데 굳이 나눈 것* 과 *나눠야 하는데 합친 것* 둘 다 미덕이 아니다.

3. **Show, don't tell.** 주석으로 설명하는 대신 코드를 짧게 만든다. 그래도 설명이 필요하면, 주석은 **WHY** 만. 텐서가 등장하면 shape 을 인라인으로 적어둔다: `# x: (B, T, C)`.

4. **Run it.** "이론적으로 동작한다"는 상태에서 멈추지 않는다. 모든 컴포넌트는 single-command 로 실행/검증 가능해야 하고, 새 기능에는 그 자리에서 돌아가는 sanity check 가 같이 들어간다. `scripts/e2e_smoke.sh` 는 거짓말을 못 하는 정직한 척도다 — 깨지면 그게 진실이다.

5. **Look at the data.** 모델 결과를 믿기 전에 입력/출력을 *눈으로 본다*. drift report 의 HTML 을 열어보고, prediction 분포를 직접 plot 한다. "metric 이 좋아 보였다"는 가장 위험한 진술이다.

6. **Loss curves first, prose later.** PR 설명은 짧게. 대신 *실제로 동작했다는 증거* (run id, metric 캡쳐, e2e smoke 통과 로그, 대시보드 스크린샷)를 우선 첨부.

7. **YOLO is fine, but only after you've read the diff.** 자신감 있는 빠른 iteration 은 환영. 단, push 전 본인 코드를 1분만 더 읽는다. 카파시는 자기 PR 도 self-review 한다.

8. **Naming matters.** `manager`, `handler`, `util`, `helper` 는 거의 항상 더 좋은 이름이 있다. `train_mlp`, `assemble_finetune_dataset`, `promote.py` 처럼 *동사 + 대상* 으로.

## 이 저장소에 적용되는 구체 규칙

- **`pipelines/components/*.py`** 는 각 함수가 *하나만* 한다. 함수 길이 80줄 넘어가면 쪼개거나, 못 쪼개면 *왜 안 쪼개지는지* 주석 한 줄.
- **PyTorch 코드** (`train_mlp.py` 류) 는 `nn.Sequential` 한 줄에 다 들어갈 정도로 단순한 게 디폴트. Lightning 의 magic 은 최소만. `forward` 는 손으로 따라갈 수 있어야 한다.
- **YAML/manifest** 는 jinja 와 helm 을 섞지 않는다. 한 파일은 한 가지 방식으로. 변수가 3개 이상이면 차라리 Python 으로 생성한다.
- **컴포넌트 사이 경계** 는 *파일 시스템* 으로 표현 (KFP `Input/OutputPath`). DB/메시지큐 같은 무거운 brokering 없이.
- **재현성** 은 lineage 5종 태그(`dataset_uri`, `dataset_hash`, `git_sha`, `kfp_run_id`, `triggered_by`)로만 검증한다. 다른 trace 시스템 추가는 5종이 *부족함을 증명한 다음에만*.
- **롤백** 은 한 명령으로 가능해야 한다. "스크립트 안 보고도 손으로 칠 수 있는" 길이의 명령. 매니페스트 스냅샷이 그 길이를 보장한다.
- **새 의존성** 은 한 줄짜리 정당화를 PR 본문에 적는다. `numpy`, `pandas`, `torch` 외엔 다 의심 대상.
- **테스트** 는 unit test 보다 *눈에 보이는 e2e* 가 먼저. `e2e_smoke.sh` 가 깨지지 않게 유지하는 게 모든 PR 의 최저 기준.

## 어시스턴트가 피해야 할 것

- 미래의 가능성을 위한 추상화 / "혹시 모르니까" 옵션. 필요해진 다음에 추가한다.
- 의례적인 try/except. 진짜 boundary (외부 API, 사용자 입력) 에서만 처리한다.
- 한 줄짜리 변경에 따라오는 "주변 정리" PR. 작업의 의도만 정확히 한다.
- 코드 = 설명. WHAT 을 적는 주석. 변수명/함수명이 이미 말해야 한다.
- 화려한 CLI / argparse 서브커맨드. 환경변수 + 단일 entrypoint 가 보통 더 정직하다.
- 4단계 inheritance, generic `BasePipelineComponent` 류. 카파시는 inheritance 를 거의 안 쓴다 — composition 도 거의 안 쓴다, 함수 호출이 디폴트.

## 작성 톤

- 한국어 응답 OK, 코드 주석/식별자는 영어.
- 자신감 있게, 짧게. 헷갈리면 헷갈린다고 명시. 거짓 자신감이 가장 비싸다.
- PR/commit 메시지는 한 줄 요약 + 본문 3~5줄. 본문은 *왜* + *어떻게 검증했는지*.
- 결과 보고는 "loss curve 가 어떻게 움직였는지" 비유로. 즉, 단정적이고 데이터 기반으로.

## 인용 (스스로에게 묻는 카파시의 문장)

- "The bitter lesson is that scale wins. So make sure your pipeline can swallow more data without breaking."
- "I want to see the data."
- "Just write the dumb thing that works first."
- "If you can't explain your model in one screen of code, you don't understand it."
- "Don't trust the loss. Trust the eval."

---
*이 파일은 어시스턴트와 사람이 모두 이 저장소에서 일관된 스타일로 일하기 위한 단일 진리원본이다. 원칙이 코드와 충돌하면 코드를 고친다, 이 파일이 아니라.*
