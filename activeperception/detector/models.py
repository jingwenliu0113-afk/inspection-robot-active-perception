"""The three COCO-pretrained detector candidates of decision 005.

Every wrapper maps an RGB uint8 image (H, W, 3) to target-class candidates
``[[confidence, x1, y1, x2, y2], ...]`` (pixels), at most ``max_det`` of them, sorted by
confidence. Settings follow decision 005 and its appendix A:

* Ultralytics (YOLOv8m, YOLO11m): ``conf=0.001, imgsz=640, max_det=100``, class filter
  before NMS output, default NMS IoU; numpy input is BGR, so RGB frames are flipped.
  Runs with ``YOLO_OFFLINE=1`` (no network, no usage analytics).
* torchvision Faster R-CNN MobileNetV3-Large FPN (``COCO_V1``): ``box_score_thresh=0.001``,
  ``box_detections_per_img=1000`` (a cap over *all* classes), then keep the top 100
  fire-hydrant boxes; default transform (min_size 800).

torch / torchvision / ultralytics are optional dependencies (``uv sync --extra detectors``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TARGET_CLASS = "fire hydrant"
MAX_DET = 100


@dataclass(frozen=True)
class Candidate:
    name: str
    family: str  # "ultralytics" | "torchvision"
    weights: str  # file name under the weights directory
    url: str
    sha256: str
    license: str


CANDIDATES: dict[str, Candidate] = {
    "yolov8m": Candidate(
        "yolov8m",
        "ultralytics",
        "yolov8m.pt",
        "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8m.pt",
        "5d4a90cdc7a21786cc59cd19778e9eafff836df9e2da32524737c7ee6efe4fe5",
        "AGPL-3.0 (code and weights; Ultralytics Enterprise License as alternative)",
    ),
    "yolo11m": Candidate(
        "yolo11m",
        "ultralytics",
        "yolo11m.pt",
        "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11m.pt",
        "d5ffc1a674953a08e11a8d21e022781b1b23a19b730afc309290bd9fb5305b95",
        "AGPL-3.0 (code and weights; Ultralytics Enterprise License as alternative)",
    ),
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


class UltralyticsDetector:
    def __init__(self, cand: Candidate, weights_path: Path, device: str, conf: float = 0.001):
        os.environ.setdefault("YOLO_OFFLINE", "1")
        from ultralytics import YOLO

        self.name = cand.name
        self.device = device
        self.conf = conf
        self.model = YOLO(str(weights_path))
        matches = [k for k, v in self.model.names.items() if v == TARGET_CLASS]
        if len(matches) != 1:
            raise ValueError(f"{cand.name}: class '{TARGET_CLASS}' not found")
        self.class_id = int(matches[0])

    def n_params(self) -> int:
        return sum(p.numel() for p in self.model.model.parameters())

    def detect(self, rgb: np.ndarray) -> list[list[float]]:
        bgr = np.ascontiguousarray(rgb[..., ::-1])
        res = self.model.predict(
            bgr,
            conf=self.conf,
            imgsz=640,
            max_det=MAX_DET,
            classes=[self.class_id],
            device=self.device,
            verbose=False,
        )[0]
        boxes = res.boxes
        xyxy = boxes.xyxy.cpu().numpy()
        conf = boxes.conf.cpu().numpy()
        cls = boxes.cls.cpu().numpy().astype(int)
        out = [
            [float(c), *(float(v) for v in b)]
            for c, b, k in zip(conf, xyxy, cls, strict=True)
            if k == self.class_id
        ]
        return sorted(out, key=lambda d: -d[0])[:MAX_DET]


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
    cls = UltralyticsDetector if cand.family == "ultralytics" else TorchvisionFRCNN
    return cls(cand, path, device)
