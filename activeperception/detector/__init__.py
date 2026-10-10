"""Detector interface. The Core detector choice is a pending decision (see NEXT.md)."""

from .base import ConstantDetector, Detector, image_area_fraction

__all__ = ["ConstantDetector", "Detector", "image_area_fraction"]
