"""PyTorch Lightning MLP 학습 컴포넌트.

- 입력: train/val npz, optional base_checkpoint_uri (fine-tune 시).
- 출력: 학습된 state_dict (.pt) + 메타.
"""
from kfp import dsl


@dsl.component(
    base_image="kfp-registry:5000/mlplatform/trainer:latest",
)
def train_mlp(
    train_npz: dsl.InputPath("Dataset"),
    val_npz: dsl.InputPath("Dataset"),
    hidden_dims: str,             # "128,64"
    epochs: int,
    lr: float,
    batch_size: int,
    base_checkpoint_uri: str,     # 빈 문자열이면 from-scratch
    model_out: dsl.OutputPath("Model"),
    metrics_out: dsl.OutputPath("Metrics"),
) -> None:
    import json
    import os
    import subprocess
    from pathlib import Path

    import numpy as np
    import pytorch_lightning as pl
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    tr = np.load(train_npz)
    va = np.load(val_npz)
    X_tr, y_tr = tr["X"], tr["y"]
    X_va, y_va = va["X"], va["y"]

    n_features = X_tr.shape[1]
    n_classes = int(max(y_tr.max(), y_va.max()) + 1)
    hidden = [int(x) for x in hidden_dims.split(",") if x.strip()]

    class MLP(pl.LightningModule):
        def __init__(self):
            super().__init__()
            layers, prev = [], n_features
            for h in hidden:
                layers += [nn.Linear(prev, h), nn.ReLU(), nn.Dropout(0.1)]
                prev = h
            layers += [nn.Linear(prev, n_classes)]
            self.net = nn.Sequential(*layers)
            self.loss = nn.CrossEntropyLoss()

        def forward(self, x): return self.net(x)
        def training_step(self, batch, _):
            x, y = batch
            logits = self(x)
            loss = self.loss(logits, y)
            self.log("train_loss", loss, prog_bar=True)
            return loss
        def validation_step(self, batch, _):
            x, y = batch
            logits = self(x)
            loss = self.loss(logits, y)
            acc = (logits.argmax(1) == y).float().mean()
            self.log_dict({"val_loss": loss, "val_acc": acc}, prog_bar=True)
        def configure_optimizers(self):
            return torch.optim.AdamW(self.parameters(), lr=lr)

    model = MLP()
    if base_checkpoint_uri:
        # MinIO 에서 base 체크포인트 받아오기
        subprocess.run(["mc", "alias", "set", "src",
                        os.environ["MINIO_ENDPOINT"],
                        os.environ["MINIO_ACCESS_KEY"],
                        os.environ["MINIO_SECRET_KEY"]], check=True)
        local = "/tmp/base.pt"
        mc_uri = "src/" + base_checkpoint_uri[len("s3://"):]
        subprocess.run(["mc", "cp", mc_uri, local], check=True)
        state = torch.load(local, map_location="cpu")
        model.load_state_dict(state, strict=False)
        print(f"[train] fine-tune from {base_checkpoint_uri}")

    def loader(X, y, shuffle):
        ds = TensorDataset(torch.from_numpy(X).float(), torch.from_numpy(y).long())
        return DataLoader(ds, batch_size=batch_size, shuffle=shuffle, num_workers=2)

    trainer = pl.Trainer(
        max_epochs=epochs,
        accelerator="auto",
        devices="auto",
        log_every_n_steps=10,
        enable_checkpointing=False,
        enable_progress_bar=False,
    )
    trainer.fit(model, loader(X_tr, y_tr, True), loader(X_va, y_va, False))

    # 모델 저장 (TorchScript + state_dict 둘 다)
    out = Path(model_out)
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "state_dict.pt")
    scripted = torch.jit.script(model.net.cpu().eval())
    scripted.save(out / "model.pt")

    meta = {
        "n_features": n_features,
        "n_classes": n_classes,
        "hidden_dims": hidden,
        "epochs": epochs,
        "lr": lr,
        "batch_size": batch_size,
        "val_loss": float(trainer.callback_metrics.get("val_loss", torch.tensor(float("nan")))),
        "val_acc":  float(trainer.callback_metrics.get("val_acc",  torch.tensor(float("nan")))),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    Path(metrics_out).write_text(json.dumps(meta))

    # TorchServe layout — KServe 의 kserve-torchserve runtime 이 /mnt/models 에서 기대하는 구조:
    #   /mnt/models/config/config.properties
    #   /mnt/models/model-store/mlp.mar
    store = out / "model-store"
    conf = out / "config"
    store.mkdir(exist_ok=True)
    conf.mkdir(exist_ok=True)
    subprocess.run([
        "torch-model-archiver",
        "--model-name", "mlp",
        "--version", "1.0",
        "--serialized-file", str(out / "model.pt"),
        "--handler", "/templates/handler.py",
        "--export-path", str(store),
        "--force",
    ], check=True)
    # KServe wrapper (parse_config) 가 model_snapshot JSON 을 요구 — 없으면 KeyError.
    snapshot = (
        '{"name":"startup.cfg","modelCount":1,"models":{"mlp":{"1.0":{'
        '"defaultVersion":true,"marName":"mlp.mar",'
        '"minWorkers":1,"maxWorkers":1,'
        '"batchSize":1,"maxBatchDelay":100,"responseTimeout":120}}}}'
    )
    # TorchServe 는 7080-7082, KServe wrapper 는 8080/8081 — 안 겹쳐야 wrapper 가 자기 server 띄움.
    (conf / "config.properties").write_text(
        "inference_address=http://0.0.0.0:7080\n"
        "management_address=http://0.0.0.0:7081\n"
        "metrics_address=http://0.0.0.0:7082\n"
        "grpc_inference_port=7070\n"
        "grpc_management_port=7071\n"
        "enable_envvars_config=true\n"
        "install_py_dep_per_model=true\n"
        "enable_metrics_api=true\n"
        "metrics_format=prometheus\n"
        "NUM_WORKERS=1\n"
        "model_store=/mnt/models/model-store\n"
        "load_models=mlp.mar\n"
        f"model_snapshot={snapshot}\n"
    )
    print(f"[train] saved model to {out}  (+ model-store/mlp.mar + config/config.properties)")
