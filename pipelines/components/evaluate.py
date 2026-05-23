"""테스트 set 평가. 게이트용 metric 산출. fine-tune 모드에서는 production 모델과 동등성/개선 비교."""
from kfp import dsl


@dsl.component(
    base_image="kfp-registry:5000/mlplatform/trainer:latest",
)
def evaluate(
    model_dir: dsl.InputPath("Model"),
    test_npz: dsl.InputPath("Dataset"),
    baseline_accuracy: float,         # 통과 임계치 (절대값) — fine-tune 시 현 prod 의 acc 를 전달
    metrics_out: dsl.OutputPath("Metrics"),
    passed: dsl.OutputPath("String"),
) -> None:
    import json
    from pathlib import Path

    import numpy as np
    import torch

    te = np.load(test_npz)
    X, y = te["X"], te["y"]

    model = torch.jit.load(str(Path(model_dir) / "model.pt"), map_location="cpu").eval()
    with torch.no_grad():
        logits = model(torch.from_numpy(X).float())
        preds = logits.argmax(1).numpy()
    acc = float((preds == y).mean())

    # 클래스별 균형도 보고 — drift 후 fine-tune 의 회귀 방지 보조 지표
    per_class = {}
    for c in sorted(set(y.tolist())):
        mask = y == c
        if mask.any():
            per_class[str(int(c))] = float((preds[mask] == c).mean())

    out = {
        "test_accuracy": acc,
        "per_class_accuracy": per_class,
        "n_test": int(len(y)),
        "baseline_accuracy": baseline_accuracy,
    }
    Path(metrics_out).write_text(json.dumps(out, indent=2))
    Path(passed).write_text("true" if acc >= baseline_accuracy else "false")
    print(f"[eval] acc={acc:.4f} baseline={baseline_accuracy:.4f} passed={acc >= baseline_accuracy}")
