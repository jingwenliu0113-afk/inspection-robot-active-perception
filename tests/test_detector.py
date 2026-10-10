import numpy as np

from activeperception.detector import ConstantDetector, image_area_fraction
from activeperception.types import Detection


def test_constant_detector_and_area_fraction():
    det = Detection(
        0.9, (10, 10, 110, 60), image_area_fraction((10, 10, 110, 60), 640, 480), (0.1, 0.07)
    )
    d = ConstantDetector((det,))
    assert d.detect(np.zeros((480, 640, 3), np.uint8)) == (det,)
    assert abs(det.area_frac - 5000 / 307200) < 1e-12
    assert image_area_fraction((5, 5, 1, 1), 640, 480) == 0.0
