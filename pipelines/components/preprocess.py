"""train/val/test 분할 + normalize. 학습 시점 분포를 reference-data 버킷에 업로드."""
from kfp import dsl


@dsl.component(
    base_image="kfp-registry:5000/mlplatform/trainer:latest",
)
def preprocess(
    input_dir: dsl.InputPath("Directory"),
    model_name: str,
    model_version: str,
    train_out: dsl.OutputPath("Dataset"),
    val_out: dsl.OutputPath("Dataset"),
    test_out: dsl.OutputPath("Dataset"),
    scaler_out: dsl.OutputPath("Artifact"),
    reference_uri: dsl.OutputPath("String"),
) -> None:
    import json
    import os
    import subprocess
    from pathlib import Path

    import numpy as np
    import pandas as pd
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    # 단순 가정: input_dir 안에 csv 단일 파일 또는 train.csv. 실제 사용 시 도메인 별 로더 작성.
    csvs = list(Path(input_dir).rglob("*.csv"))
    assert csvs, f"no csv under {input_dir}"
    df = pd.concat([pd.read_csv(p) for p in csvs], ignore_index=True)
    assert "label" in df.columns, "expected a 'label' column"

    X = df.drop(columns=["label"]).values.astype(np.float32)
    y = df["label"].values
    X_tr, X_rest, y_tr, y_rest = train_test_split(X, y, test_size=0.3, random_state=42, stratify=y if y.dtype.kind in "iub" else None)
    X_va, X_te, y_va, y_te = train_test_split(X_rest, y_rest, test_size=0.5, random_state=42)

    scaler = StandardScaler().fit(X_tr)
    X_tr, X_va, X_te = scaler.transform(X_tr), scaler.transform(X_va), scaler.transform(X_te)

    for path, X, y in [(train_out, X_tr, y_tr), (val_out, X_va, y_va), (test_out, X_te, y_te)]:
        np.savez_compressed(path, X=X, y=y)

    # scaler 직렬화
    import joblib
    joblib.dump(scaler, scaler_out)

    # reference 분포 통계 (Evidently 가 비교에 사용)
    feature_cols = [c for c in df.columns if c != "label"]
    ref_df = pd.DataFrame(scaler.transform(X), columns=feature_cols)
    ref_df["label"] = y
    ref_dir = Path("/tmp/reference")
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_path = ref_dir / "reference.parquet"
    ref_df.to_parquet(ref_path)

    meta = {
        "model_name": model_name,
        "model_version": model_version,
        "n_features": X.shape[1],
        "feature_cols": feature_cols,
        "n_train": len(X_tr),
        "n_val":   len(X_va),
        "n_test":  len(X_te),
    }
    (ref_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # MinIO 업로드
    subprocess.run(["mc", "alias", "set", "dst",
                    os.environ["MINIO_ENDPOINT"],
                    os.environ["MINIO_ACCESS_KEY"],
                    os.environ["MINIO_SECRET_KEY"]], check=True)
    target = f"dst/reference-data/{model_name}/{model_version}/"
    subprocess.run(["mc", "cp", "--recursive", str(ref_dir) + "/", target], check=True)

    Path(reference_uri).write_text(f"s3://reference-data/{model_name}/{model_version}/")
    print(f"[preprocess] reference uploaded to {target}")
