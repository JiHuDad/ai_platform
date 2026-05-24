"""TorchServe handler for MLP — KServe v1 inference format.

Input  (POST /v1/models/mlp:predict):
  {"instances": [[5.1, 3.5, 1.4, 0.2], ...]}
Output:
  {"predictions": [0, 0, ...]}

archive 생성 시 --serialized-file 로 scripted model.pt 사용 — model class 정의는 불필요.
"""
import json
import torch
from ts.torch_handler.base_handler import BaseHandler


class MLPHandler(BaseHandler):
    def preprocess(self, data):
        # data 는 list of dicts: [{"body": <bytes|str|dict>}, ...]
        req = data[0]
        body = req.get("body", req.get("data", req))
        if isinstance(body, (bytes, bytearray)):
            body = json.loads(body)
        elif isinstance(body, str):
            body = json.loads(body)
        # KServe v1: {"instances": [[...], ...]}, v2: {"inputs": [...]}
        instances = body.get("instances") or body.get("inputs") or body
        return torch.tensor(instances, dtype=torch.float32)

    def inference(self, data, *args, **kwargs):
        with torch.no_grad():
            return self.model(data)

    def postprocess(self, data):
        preds = data.argmax(dim=1).tolist()
        return [{"predictions": preds}]
