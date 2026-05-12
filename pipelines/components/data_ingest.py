"""MinIO → 로컬 PVC 로 데이터셋 복사 + 무결성 체크 컴포넌트."""
from kfp import dsl


@dsl.component(
    base_image="harbor.mlplatform.local/mlplatform/trainer:latest",
    packages_to_install=[],
)
def data_ingest(
    dataset_uri: str,
    output_dir: dsl.OutputPath("Directory"),
    dataset_hash: dsl.OutputPath("String"),
) -> None:
    """`dataset_uri` (s3://datasets/...) 를 output_dir 로 복사하고 해시를 계산한다."""
    import hashlib
    import os
    import subprocess
    from pathlib import Path

    os.makedirs(output_dir, exist_ok=True)

    # mc alias 등록 (Pod 환경변수에서 자격증명 읽음)
    subprocess.run(
        [
            "mc", "alias", "set", "src",
            os.environ["MINIO_ENDPOINT"],
            os.environ["MINIO_ACCESS_KEY"],
            os.environ["MINIO_SECRET_KEY"],
        ],
        check=True,
    )

    # s3://bucket/path → mc 가 이해하는 src/bucket/path 로 치환
    assert dataset_uri.startswith("s3://"), dataset_uri
    mc_uri = "src/" + dataset_uri[len("s3://"):]

    subprocess.run(["mc", "cp", "--recursive", mc_uri, output_dir + "/"], check=True)

    # 디렉토리 전체 SHA256 (정렬된 파일 목록 기준)
    h = hashlib.sha256()
    for p in sorted(Path(output_dir).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(output_dir)).encode())
            h.update(p.read_bytes())
    digest = h.hexdigest()

    Path(dataset_hash).write_text(digest)
    print(f"[ingest] {dataset_uri} → {output_dir} sha256={digest[:12]}")
