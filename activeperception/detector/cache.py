"""Per-frame detection cache (decision 007): every detector runs once per rendered frame.

JSONL: the first line is a header ``{"detector": ..., "meta": {...}}``; every other line is
``{"episode_id", "vp_id", "dets": [[confidence, x1, y1, x2, y2], ...]}`` for the target
class only, sorted by confidence (descending). ``min_confidence`` filters at read time,
so one low-threshold cache serves both the detector evaluation and the experiment.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..types import Detection
from .base import image_area_fraction


def make_detection(conf: float, bbox, width: int, height: int) -> Detection:
    x1, y1, x2, y2 = (float(v) for v in bbox)
    return Detection(
        confidence=float(conf),
        bbox=(x1, y1, x2, y2),
        area_frac=image_area_fraction((x1, y1, x2, y2), width, height),
        center_uv=((x1 + x2) / 2.0 / width, (y1 + y2) / 2.0 / height),
    )


class DetectionCache:
    def __init__(
        self,
        detector: str,
        meta: dict | None = None,
        image_size: tuple[int, int] = (640, 480),
        min_confidence: float = 0.0,
    ):
        self.detector = detector
        self.meta = dict(meta or {})
        self.width, self.height = image_size
        self.min_confidence = min_confidence
        self._rows: dict[tuple[str, int], list[list[float]]] = {}

    def put(self, episode_id: str, vp_id: int, dets: list[list[float]]) -> None:
        self._rows[(episode_id, int(vp_id))] = sorted(
            ([float(v) for v in d] for d in dets), key=lambda d: -d[0]
        )

    def has(self, episode_id: str, vp_id: int) -> bool:
        return (episode_id, int(vp_id)) in self._rows

    def raw(self, episode_id: str, vp_id: int) -> list[list[float]]:
        return self._rows[(episode_id, int(vp_id))]

    def keys(self) -> list[tuple[str, int]]:
        return sorted(self._rows)

    def get(self, episode_id: str, vp_id: int) -> tuple[Detection, ...]:
        try:
            rows = self._rows[(episode_id, int(vp_id))]
        except KeyError:
            raise KeyError(f"{self.detector}: no detections for {episode_id} vp {vp_id}") from None
        return tuple(
            make_detection(r[0], r[1:5], self.width, self.height)
            for r in rows
            if r[0] >= self.min_confidence
        )

    def with_min_confidence(self, min_confidence: float) -> DetectionCache:
        out = DetectionCache(self.detector, self.meta, (self.width, self.height), min_confidence)
        out._rows = self._rows
        return out

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        with open(tmp, "w") as f:
            header = {
                "detector": self.detector,
                "meta": self.meta,
                "image_size": [self.width, self.height],
            }
            f.write(json.dumps(header, sort_keys=True) + "\n")
            for (eid, vid), dets in sorted(self._rows.items()):
                row = {"episode_id": eid, "vp_id": vid, "dets": dets}  # full precision
                f.write(json.dumps(row) + "\n")
        tmp.replace(path)

    @classmethod
    def load(cls, path: str | Path, min_confidence: float = 0.0) -> DetectionCache:
        with open(path) as f:
            header = json.loads(f.readline())
            cache = cls(
                header["detector"],
                header.get("meta"),
                tuple(header.get("image_size", (640, 480))),
                min_confidence,
            )
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    cache.put(row["episode_id"], row["vp_id"], row["dets"])
        return cache
