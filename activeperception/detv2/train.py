"""Fine-tune detector-v1 (FRCNN-MobileNetV3-Large-FPN, COCO) with hard negatives (decision 027).

    # smoke (any machine, minutes):
    uv run --extra detectors python -m activeperception.detv2.train --train data/detv2/train.csv \\
        --out runs/detv2/smoke --device cpu --epochs 1 --limit 16
    # real run (RTX 5070 Ti, inside the shared GPU lock - MACHINE_POLICY):
    uv run --extra detectors python -m activeperception.detv2.train --train data/detv2/train.csv \\
        --out runs/detv2/<config> --device cuda --config <config>

Same architecture, class list and output format as detector-v1: only the weights change, so the
rest of the pipeline (decision rule, thresholds, zone gating) is untouched. Images are used at the
camera-equivalent pixel count (R0a / v3). A hydrant box is class ``fire hydrant`` (COCO index);
every other pixel is background, so hard negatives are images with no target.

Writes ``<out>/weights.pth`` (+ sha256) and ``<out>/train_log.json``. Weights never enter git.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .. import r0a
from ..detector.models import CANDIDATES, TARGET_CLASS, resolve_device, sha256_file
from .data import image_path


@dataclass(frozen=True)
class TrainConfig:
    """The pre-registered grid (decision 027 §4); one is chosen on dev only."""

    name: str
    lr: float = 0.005
    epochs: int = 8
    batch: int = 4
    pos_fraction: float = 0.5  # share of positive images in every batch
    trainable_backbone_layers: int = 3
    weight_decay: float = 1e-4
    warmup_iters: int = 200
    seed: int = 0


CONFIGS = {
    "base": TrainConfig("base"),
    "lowlr": TrainConfig("lowlr", lr=0.0025),
    "negheavy": TrainConfig("negheavy", pos_fraction=0.33),
}


def boxes_px(row: dict, scale: float, width: int, height: int) -> np.ndarray:
    """Manifest boxes -> pixels of the (resized) training image."""
    b = np.array(json.loads(row["boxes"]) or np.zeros((0, 4)), dtype=np.float32).reshape(-1, 4)
    if row["source"].startswith("oi-"):  # normalised (x1, y1, x2, y2)
        b = b * np.array([width, height, width, height], dtype=np.float32)
    else:  # COCO pixels of the original image
        b = b * scale
    b[:, [0, 2]] = b[:, [0, 2]].clip(0, width)
    b[:, [1, 3]] = b[:, [1, 3]].clip(0, height)
    return b[(b[:, 2] - b[:, 0] >= 2) & (b[:, 3] - b[:, 1] >= 2)]


def load_example(row: dict, images: Path) -> tuple[np.ndarray, np.ndarray]:
    rgb, _ = r0a.load_rgb(image_path(images, row))
    img = r0a.camera_equivalent(rgb)
    scale = img.shape[1] / rgb.shape[1]
    return img, boxes_px(row, scale, img.shape[1], img.shape[0])


def batches(rows: list[dict], cfg: TrainConfig, rng: np.random.Generator):
    """One epoch = every negative once; positives re-drawn to the configured share."""
    pos = [r for r in rows if r["label"] == "pos"]
    neg = [r for r in rows if r["label"] == "neg"]
    n_pos = max(1, round(len(neg) * cfg.pos_fraction / (1 - cfg.pos_fraction)))
    pick = list(rng.permutation(neg)) + list(rng.choice(pos, size=n_pos, replace=n_pos > len(pos)))
    order = rng.permutation(len(pick))
    for i in range(0, len(order), cfg.batch):
        yield [pick[j] for j in order[i : i + cfg.batch]]


def freeze_batchnorm(module) -> None:
    """BatchNorm2d -> FrozenBatchNorm2d with the same statistics (batch 4 must not update them)."""
    import torch
    from torchvision.ops import FrozenBatchNorm2d

    for name, child in module.named_children():
        if isinstance(child, torch.nn.BatchNorm2d):
            frozen = FrozenBatchNorm2d(child.num_features, eps=child.eps)
            for k in ("weight", "bias", "running_mean", "running_var"):
                getattr(frozen, k).copy_(getattr(child, k).detach())
            setattr(module, name, frozen)
        else:
            freeze_batchnorm(child)


def build_model(weights_dir: Path, cfg: TrainConfig):
    import torch
    from torchvision.models.detection import (
        FasterRCNN_MobileNet_V3_Large_FPN_Weights,
        fasterrcnn_mobilenet_v3_large_fpn,
    )

    cand = CANDIDATES["frcnn-mnv3"]
    path = weights_dir / cand.weights
    if sha256_file(path) != cand.sha256:
        raise ValueError(f"{path}: not the frozen detector-v1 weights")
    meta = FasterRCNN_MobileNet_V3_Large_FPN_Weights.COCO_V1.meta
    model = fasterrcnn_mobilenet_v3_large_fpn(
        weights=None,
        weights_backbone=None,
        num_classes=len(meta["categories"]),
        trainable_backbone_layers=cfg.trainable_backbone_layers,
    )
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    # built without torchvision's pretrained path, so do what it would have done: frozen batch
    # norm in the backbone and only the last ``trainable_backbone_layers`` stages trainable
    freeze_batchnorm(model.backbone)
    body = list(model.backbone.body.children())
    stages = [0] + [i for i, b in enumerate(body) if getattr(b, "_is_cn", False)] + [len(body) - 1]
    k = cfg.trainable_backbone_layers
    for layer in body[: len(body) if k == 0 else stages[len(stages) - k]]:
        for p in layer.parameters():
            p.requires_grad_(False)
    return model, meta["categories"].index(TARGET_CLASS)


def train(
    rows: list[dict],
    images: Path,
    out: Path,
    cfg: TrainConfig,
    device: str,
    weights_dir: Path,
    limit: int | None = None,
) -> dict:
    import torch

    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    if limit:
        rows = [r for r in rows if r["label"] == "pos"][: limit // 2] + [
            r for r in rows if r["label"] == "neg"
        ][: limit - limit // 2]
    model, cls = build_model(weights_dir, cfg)
    model.to(device).train()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.SGD(params, lr=cfg.lr, momentum=0.9, weight_decay=cfg.weight_decay)
    n_iter = cfg.epochs * math.ceil(
        (sum(r["label"] == "neg" for r in rows) / (1 - cfg.pos_fraction)) / cfg.batch
    )

    def lr_at(it: int) -> float:
        warm = min(1.0, (it + 1) / max(1, cfg.warmup_iters))
        return cfg.lr * warm * 0.5 * (1 + math.cos(math.pi * min(it, n_iter) / max(1, n_iter)))

    log, it, t0 = [], 0, time.time()
    for epoch in range(cfg.epochs):
        losses = []
        for batch in batches(rows, cfg, rng):
            imgs, targets = [], []
            for row in batch:
                img, boxes = load_example(row, images)
                if rng.random() < 0.5:  # horizontal flip
                    img = img[:, ::-1]
                    w = img.shape[1]
                    boxes = boxes[:, [2, 1, 0, 3]] * [-1, 1, -1, 1] + [w, 0, w, 0]
                x = torch.from_numpy(np.ascontiguousarray(img)).permute(2, 0, 1).float() / 255
                imgs.append(x.to(device))
                bx = torch.as_tensor(boxes, dtype=torch.float32).reshape(-1, 4)
                lab = torch.full((len(bx),), cls, dtype=torch.int64)
                targets.append({"boxes": bx.to(device), "labels": lab.to(device)})
            for g in opt.param_groups:
                g["lr"] = lr_at(it)
            loss = sum(model(imgs, targets).values())
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(loss.item())
            it += 1
        log.append(
            {
                "epoch": epoch,
                "iters": it,
                "loss_mean": float(np.mean(losses)),
                "elapsed_s": time.time() - t0,
            }
        )
        print(json.dumps(log[-1]), flush=True)
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "weights.pth")
    rec = {
        "config": asdict(cfg),
        "device": device,
        "n_rows": len(rows),
        "iters": it,
        "log": log,
        "torch": torch.__version__,
        "weights_sha256": sha256_file(out / "weights.pth"),
        "init": CANDIDATES["frcnn-mnv3"].sha256,
    }
    (out / "train_log.json").write_text(json.dumps(rec, indent=1) + "\n")
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.detv2.train")
    ap.add_argument("--train", required=True)
    ap.add_argument("--images", default="data/raw/detv2")
    ap.add_argument("--weights-dir", default="models")
    ap.add_argument("--config", default="base", choices=sorted(CONFIGS))
    ap.add_argument("--epochs", type=int)
    ap.add_argument("--limit", type=int, help="smoke runs: this many images")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if "test" in Path(args.train).name:
        raise SystemExit("never train on the test manifest (decision 027)")
    cfg = CONFIGS[args.config]
    if args.epochs:
        from dataclasses import replace

        cfg = replace(cfg, epochs=args.epochs)
    rows = r0a.read_csv(Path(args.train))
    device = resolve_device(args.device)
    rec = train(
        rows, Path(args.images), Path(args.out), cfg, device, Path(args.weights_dir), args.limit
    )
    print(json.dumps({k: rec[k] for k in ("device", "iters", "weights_sha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
