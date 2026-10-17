"""The COCO-pretrained detector of decision 005 (the frozen ``detector-v1``).

The wrapper maps an RGB uint8 image (H, W, 3) to target-class candidates
``[[confidence, x1, y1, x2, y2], ...]`` (pixels), at most ``max_det`` of them, sorted by
confidence. Settings follow decision 005 and its appendix A:

* torchvision Faster R-CNN MobileNetV3-Large FPN (``COCO_V1``): ``box_score_thresh=0.001``,
  ``box_detections_per_img=1000`` (a cap over *all* classes), then keep the top 100
  fire-hydrant boxes; default transform (min_size 800).

Decision 005 also compared YOLOv8m and YOLO11m (Ultralytics, AGPL-3.0). Their adapter and the
``ultralytics`` dependency were removed on 2026-10-17 so that the repository stays BSD-3-Clause;
their recorded detections stay in ``results/detector-selection/caches/`` (sealed), but they can no
longer be re-run from this repository (README, "授權").

torch / torchvision are optional dependencies (``uv sync --extra detectors``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

TARGET_CLASS = "fire hydrant"
MAX_DET = 100


@dataclass(frozen=True)
class Candidate:
    name: str
    family: str  # "torchvision"
    weights: str  # file name under the weights directory
    url: str
    sha256: str
    license: str


CANDIDATES: dict[str, Candidate] = {
    "frcnn-mnv3": Candidate(
        "frcnn-mnv3",
        "torchvision",
        "fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth",
        "https://download.pytorch.org/models/fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth",
        "fb6a3cc702b1df54c18a44b26708cd083614211062d0c36d2ca7bf9270df3533",
        "BSD-3-Clause (torchvision code); pretrained weights: COCO-derived, no extra terms",
    ),
}


def sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_device(device: str) -> str:
    import torch

    if device != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def synchronize(device: str) -> None:
    import torch

    if device.startswith("cuda"):
        torch.cuda.synchronize()
    elif device == "mps":
        torch.mps.synchronize()


class TorchvisionFRCNN:
    def __init__(self, cand: Candidate, weights_path: Path, device: str, conf: float = 0.001):
        import torch
        from torchvision.models.detection import (
            FasterRCNN_MobileNet_V3_Large_FPN_Weights,
            fasterrcnn_mobilenet_v3_large_fpn,
        )

        self.name = cand.name
        self.device = device
        meta = FasterRCNN_MobileNet_V3_Large_FPN_Weights.COCO_V1.meta
        self.class_id = meta["categories"].index(TARGET_CLASS)
        model = fasterrcnn_mobilenet_v3_large_fpn(
            weights=None,
            weights_backbone=None,
            num_classes=len(meta["categories"]),
            box_score_thresh=conf,
            box_detections_per_img=1000,
        )
        state = torch.load(weights_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        self.model = model.eval().to(device)
        self._torch = torch

    def n_params(self) -> int:
        return sum(p.numel() for p in self.model.parameters())

    def detect(self, rgb: np.ndarray) -> list[list[float]]:
        torch = self._torch
        x = torch.from_numpy(np.ascontiguousarray(rgb)).permute(2, 0, 1).float().div(255.0)
        with torch.inference_mode():
            out = self.model([x.to(self.device)])[0]
        keep = out["labels"] == self.class_id
        scores = out["scores"][keep].cpu().numpy()
        boxes = out["boxes"][keep].cpu().numpy()
        dets = [[float(s), *(float(v) for v in b)] for s, b in zip(scores, boxes, strict=True)]
        return sorted(dets, key=lambda d: -d[0])[:MAX_DET]


def load_detector(name: str, weights_dir: str | Path, device: str = "auto", verify: bool = True):
    cand = CANDIDATES[name]
    path = Path(weights_dir) / cand.weights
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; download {cand.url}")
    if verify and sha256_file(path) != cand.sha256:
        raise ValueError(f"{path}: sha256 mismatch (expected {cand.sha256})")
    device = resolve_device(device)
    return TorchvisionFRCNN(cand, path, device)
