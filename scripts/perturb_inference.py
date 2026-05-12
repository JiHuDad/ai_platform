"""분포 어긋난 추론 트래픽을 생성하여 drift 시뮬레이션.

원본 iris feature 의 평균을 의도적으로 시프트한 후 mlp 엔드포인트로 1000건 요청.
"""
from __future__ import annotations

import argparse
import json
import time

import httpx
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://mlp.mlplatform.local/v1/models/mlp:predict")
    p.add_argument("--n", type=int, default=1000)
    p.add_argument("--shift", type=float, default=3.0,
                   help="Feature mean shift (sigma units) 어긋남 정도")
    p.add_argument("--qps", type=float, default=10.0)
    args = p.parse_args()

    rng = np.random.default_rng(seed=42)
    # iris: 4 feature, 학습 시 정규화되었다고 가정 (mean≈0, std≈1).
    sent, errs = 0, 0
    interval = 1.0 / args.qps
    with httpx.Client(timeout=5.0, verify=False) as c:
        for _ in range(args.n):
            x = rng.normal(loc=args.shift, scale=1.0, size=4).tolist()
            body = {"instances": [x]}
            try:
                r = c.post(args.url, json=body)
                sent += 1
                if r.status_code >= 400:
                    errs += 1
            except Exception as e:
                errs += 1
                print("err", e)
            time.sleep(interval)
    print(json.dumps({"sent": sent, "errors": errs, "shift_sigma": args.shift}))


if __name__ == "__main__":
    main()
