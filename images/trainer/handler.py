"""TorchServe handler for MLP — KServe v1 + v2 (OIP) + torchserve direct.

KServe wrapper 는 v2 OIP envelope 의 `inputs[0]` 을 *list 로 unpack* 해서 전달한다.
즉 우리가 받는 data 는 다음 형태 중 하나:

  1) KServe v2 (after wrapper unpack):  [{"name": "...", "shape": [N,D], "datatype":"FP32", "data":[[...]]}]
  2) KServe v1 direct:                  [{"body": b'{"instances":[[...]]}'}]
  3) torchserve native:                 [{"body": b'<json>'}] or [{"data": b'...'}]

Output: KServe wrapper 가 다시 envelope 으로 래핑.
"""
import json
import torch
from ts.torch_handler.base_handler import BaseHandler


def _to_2d(data, shape):
    """data 가 flat list 면 shape=[N,D] 로 reshape, 이미 2D 면 그대로."""
    if not data:
        return data
    # 이미 nested 면 그대로
    if isinstance(data[0], (list, tuple)):
        return data
    if shape and len(shape) == 2 and len(data) == shape[0] * shape[1]:
        n, d = shape
        return [data[i * d:(i + 1) * d] for i in range(n)]
    return [data]   # 1D fallback


class MLPHandler(BaseHandler):
    def preprocess(self, data):
        if not data:
            return torch.empty(0)

        req = data[0]

        # Shape 1: req 가 dict — torchserve direct
        if isinstance(req, dict):
            body = req.get("body") or req.get("data") or req
            if isinstance(body, (bytes, bytearray)):
                body = json.loads(body)
            elif isinstance(body, str):
                body = json.loads(body)

            if isinstance(body, dict):
                if "instances" in body:                     # KServe v1
                    instances = body["instances"]
                elif "inputs" in body:                       # KServe v2 envelope
                    inp = body["inputs"][0]
                    instances = _to_2d(inp.get("data") or [], inp.get("shape"))
                else:
                    instances = body
            elif isinstance(body, list):
                # body 가 그냥 list of vectors
                instances = body
            else:
                instances = [body]

        # Shape 2: req 가 dict 인데 KServe wrapper 가 *envelope unpack* 으로 inputs[i] 직접 전달
        # (req 가 {"name":..., "shape":..., "data":...} 형태)
        if isinstance(req, dict) and "data" in req and "shape" in req:
            instances = _to_2d(req["data"], req.get("shape"))

        # 최종 변환
        if isinstance(instances, list) and instances and not isinstance(instances[0], (list, tuple)):
            instances = [instances]   # 1D → wrap

        return torch.tensor(instances, dtype=torch.float32)

    def inference(self, data, *args, **kwargs):
        with torch.no_grad():
            return self.model(data)

    def postprocess(self, data):
        preds = data.argmax(dim=1).tolist()
        return [{"predictions": preds}]
