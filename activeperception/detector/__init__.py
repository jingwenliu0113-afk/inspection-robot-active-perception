"""Detectors. ``detector-v1`` (decision 005 appendix B) is torchvision FRCNN-MobileNetV3."""

from .base import ConstantDetector, Detector, image_area_fraction

DETECTOR_VERSION = "detector-v1"
FROZEN_DETECTOR = "frcnn-mnv3"  # key of activeperception.detector.models.CANDIDATES

__all__ = [
    "DETECTOR_VERSION",
    "FROZEN_DETECTOR",
    "ConstantDetector",
    "Detector",
    "image_area_fraction",
]
