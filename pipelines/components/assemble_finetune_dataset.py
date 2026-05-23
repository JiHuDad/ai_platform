"""drift 윈도의 라벨링된 inference + 기존 train set 을 결합하여 fine-tune 셋 생성.

가정: 라벨링 시스템이 `s3://inference-logs/<model>/labeled/` 에 NDJSON 으로 결과를 적재.
부재 시 self-training (pseudo label) 옵션도 지원 (`PSEUDO_LABEL=1`).
"""
from kfp import dsl


@dsl.component(
    base_image="kfp-registry:5000/mlplatform/trainer:latest",
)
def assemble_finetune_dataset(
    model_name: str,
    base_dataset_uri: str,
    window_hours: int,
    output_dir: dsl.OutputPath("Directory"),
    new_dataset_uri_out: dsl.OutputPath("String"),
    dataset_hash_out: dsl.OutputPath("String"),
) -> None:
    import hashlib
    import json
    import os
    import subprocess
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    import pandas as pd

    os.makedirs(output_dir, exist_ok=True)
    subprocess.run(["mc", "alias", "set", "src",
                    os.environ["MINIO_ENDPOINT"],
                    os.environ["MINIO_ACCESS_KEY"],
                    os.environ["MINIO_SECRET_KEY"]], check=True)

    # 1) base dataset 가져오기
    base = "/tmp/base"
    os.makedirs(base, exist_ok=True)
    subprocess.run(["mc", "cp", "--recursive",
                    "src/" + base_dataset_uri[len("s3://"):], base + "/"], check=True)

    csvs = list(Path(base).rglob("*.csv"))
    base_df = pd.concat([pd.read_csv(p) for p in csvs], ignore_index=True)

    # 2) 라벨링된 inference NDJSON 수집
    labeled = "/tmp/labeled"
    os.makedirs(labeled, exist_ok=True)
    proc = subprocess.run(
        ["mc", "cp", "--recursive", f"src/inference-logs/{model_name}/labeled/", labeled + "/"],
        capture_output=True, text=True,
    )
    rows: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    for p in Path(labeled).rglob("*.jsonl"):
        if datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) < cutoff:
            continue
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            inst = r.get("input") or r.get("instances")
            lbl = r.get("label") or r.get("ground_truth")
            if inst is None or lbl is None:
                continue
            if isinstance(inst, list) and inst and isinstance(inst[0], list):
                for arr in inst:
                    row = {f"f{i}": v for i, v in enumerate(arr)}
                    row["label"] = lbl
                    rows.append(row)
            elif isinstance(inst, dict):
                row = dict(inst); row["label"] = lbl
                rows.append(row)

    if rows:
        new_df = pd.DataFrame(rows)
        # 컬럼 정렬을 base 와 맞춤
        new_df = new_df.reindex(columns=base_df.columns).dropna(subset=["label"])
        combined = pd.concat([base_df, new_df], ignore_index=True)
        print(f"[assemble] base={len(base_df)} new={len(new_df)} combined={len(combined)}")
    else:
        combined = base_df
        print(f"[assemble] no labeled data in window — using base only (n={len(base_df)})")

    out = Path(output_dir) / "train.csv"
    combined.to_csv(out, index=False)

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    Path(dataset_hash_out).write_text(digest)

    # 신규 데이터셋 버킷에 업로드 (재현성)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    target = f"src/datasets/{model_name}/finetune-{ts}/"
    subprocess.run(["mc", "cp", "--recursive", str(output_dir) + "/", target], check=True)
    Path(new_dataset_uri_out).write_text(target.replace("src/", "s3://"))
    print(f"[assemble] uploaded {target} sha={digest[:12]}")
