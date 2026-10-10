from __future__ import annotations

from typing import Protocol

import numpy as np

from ..types import Detection


class Detector(Protocol):
    """Maps an RGB image (H, W, 3, uint8) to zero or more detections of the target class."""

    name: str

    def detect(self, image: np.ndarray) -> tuple[Detection, ...]: ...


def image_area_fraction(bbox: tuple[float, float, float, float], width: int, height: int) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1) / float(width * height)


class ConstantDetector:
    """Test double: always returns the configured detections."""

    name = "constant"

    def __init__(self, detections: tuple[Detection, ...] = ()):
        self._detections = detections

    def detect(self, image: np.ndarray) -> tuple[Detection, ...]:
        return self._detections
