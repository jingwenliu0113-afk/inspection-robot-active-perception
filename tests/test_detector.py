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


def test_no_agpl_detector_dependency():
    """The repository is BSD-3-Clause: the YOLO adapter and ``ultralytics`` (AGPL-3.0) were
    removed before publication (README, "授權"); the frozen detector-v1 is torchvision's."""
    import re
    import tomllib
    from pathlib import Path

    from activeperception.detector import FROZEN_DETECTOR
    from activeperception.detector.models import CANDIDATES

    root = Path(__file__).resolve().parents[1]
    assert set(CANDIDATES) == {FROZEN_DETECTOR}
    assert all(c.family == "torchvision" for c in CANDIDATES.values())
    deps = tomllib.loads((root / "pyproject.toml").read_text())
    listed = [d for group in deps["project"]["optional-dependencies"].values() for d in group]
    listed += deps["project"]["dependencies"] + deps["dependency-groups"]["dev"]
    assert not [d for d in listed if d.lower().startswith("ultralytics")]
    imports = re.compile(r"^\s*(import|from)\s+ultralytics\b", re.M)
    for path in [*root.glob("activeperception/**/*.py"), *root.glob("tools/*.py")]:
        assert not imports.search(path.read_text()), path
    assert (root / "LICENSE").read_text().startswith("BSD 3-Clause License")
