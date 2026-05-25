"""신규 모델을 'canary' 변형으로 배포 (KServe InferenceService) + Istio VS 초기 10/90.

`promote_pipeline` 이 step-up 을 담당하므로 여기서는 weight=10 으로 시작만 시킨다.
이전 manifest 는 MinIO `serving-manifests/` 에 스냅샷.
"""
from kfp import dsl


@dsl.component(
    base_image="kfp-registry:5000/mlplatform/trainer:latest",
)
def deploy_canary(
    model_name: str,
    model_version: str,
    storage_uri: str,
    initial_canary_weight: int,
    deployed_revision_out: dsl.OutputPath("String"),
) -> None:
    """canary InferenceService 적용 + VirtualService weight 패치."""
    import json
    import os
    import subprocess
    from datetime import datetime
    from pathlib import Path

    import yaml
    from jinja2 import Template

    serving_ns = os.environ.get("SERVING_NS", "serving")
    revision = f"{model_name}-v{model_version}"

    # 1) InferenceService canary 변형 (jinja 렌더)
    is_tmpl = Path("/templates/inferenceservice.yaml.j2").read_text()
    is_yaml = Template(is_tmpl).render(
        name=f"{model_name}-canary",
        base_name=model_name,           # mlp.yaml.j2 의 labels.app — 누락 시 Undefined → 빈 라벨 → kubectl apply 거부.
        namespace=serving_ns,
        variant="canary",
        model_format="pytorch",
        storage_uri=storage_uri,
        model_revision=revision,
        service_account="kserve-s3",
    )
    Path("/tmp/canary.yaml").write_text(is_yaml)
    subprocess.run(["kubectl", "apply", "-f", "/tmp/canary.yaml"], check=True)

    # 2) VirtualService weight 업데이트 (없으면 생성)
    # stable predictor service 부재 시 canary 100/stable 0 — 모든 트래픽이 canary 로 (첫 배포).
    stable_svc_check = subprocess.run(
        ["kubectl", "-n", serving_ns, "get", "svc", f"{model_name}-stable-predictor"],
        capture_output=True,
    )
    if stable_svc_check.returncode == 0:
        sw, cw = 100 - initial_canary_weight, initial_canary_weight
        print(f"[deploy] stable predictor 존재 — weight stable={sw}/canary={cw}")
    else:
        sw, cw = 0, 100
        print(f"[deploy] stable predictor 부재 — weight stable=0/canary=100")

    vs_tmpl = Path("/templates/virtualservice.yaml.j2").read_text()
    vs_yaml = Template(vs_tmpl).render(
        name=model_name,
        namespace=serving_ns,
        host=f"{model_name}.mlplatform.local",
        stable_host=f"{model_name}-stable-predictor.{serving_ns}.svc.cluster.local",
        canary_host=f"{model_name}-canary-predictor.{serving_ns}.svc.cluster.local",
        stable_weight=sw,
        canary_weight=cw,
        canary_revision=revision,
    )
    Path("/tmp/vs.yaml").write_text(vs_yaml)
    subprocess.run(["kubectl", "apply", "-f", "/tmp/vs.yaml"], check=True)

    # 3) MinIO 에 manifest 스냅샷 (롤백용)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    snap_dir = f"/tmp/snap-{ts}"
    Path(snap_dir).mkdir()
    Path(f"{snap_dir}/canary-isvc.yaml").write_text(is_yaml)
    Path(f"{snap_dir}/virtualservice.yaml").write_text(vs_yaml)
    # 현재 stable 의 InferenceService 도 함께 캡쳐 (롤백 기준점)
    try:
        r = subprocess.run(
            ["kubectl", "-n", serving_ns, "get", "isvc", f"{model_name}-stable", "-o", "yaml"],
            capture_output=True, text=True, check=True,
        )
        Path(f"{snap_dir}/stable-isvc.yaml").write_text(r.stdout)
    except subprocess.CalledProcessError:
        print("[deploy] no current stable — first deploy")

    subprocess.run(["mc", "alias", "set", "dst",
                    os.environ["MINIO_ENDPOINT"],
                    os.environ["MINIO_ACCESS_KEY"],
                    os.environ["MINIO_SECRET_KEY"]], check=True)
    subprocess.run(["mc", "cp", "--recursive", snap_dir + "/",
                    f"dst/serving-manifests/{model_name}/{ts}/"], check=True)

    Path(deployed_revision_out).write_text(revision)
    print(f"[deploy] canary {revision} applied at weight={initial_canary_weight}, snapshot {ts}")
