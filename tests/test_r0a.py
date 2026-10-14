"""R0a (decision 020): selection from metadata only, frozen thresholds, metrics."""

import json

import numpy as np
import pytest

from activeperception import frozen_v2, r0a


def box(xyxy=(0.1, 0.1, 0.5, 0.6), occ=0, trunc=0, group=0, dep=0):
    return {
        "xyxy": list(xyxy),
        "IsOccluded": occ,
        "IsTruncated": trunc,
        "IsGroupOf": group,
        "IsDepiction": dep,
    }


def test_thresholds_are_the_frozen_decision_v2_ones():
    assert r0a.TAU_PRESENT == frozen_v2.DECISION_V2.tau_present == 0.7
    assert r0a.TAU_ABSENT == frozen_v2.DECISION_V2.tau_absent == 0.02


@pytest.mark.parametrize(
    ("boxes", "expected"),
    [
        ([box()], "clear"),
        ([box((0.1, 0.1, 0.2, 0.2))], "small"),  # 1% of the image
        ([box(trunc=1)], "truncated"),
        ([box(occ=1, trunc=1)], "occluded"),
        ([box(dep=1)], "depiction"),
        ([box(group=1)], "group-only"),
        ([box(occ=-1)], "unknown"),
        # the primary box is the largest real single box
        ([box((0.0, 0.0, 0.9, 0.9), dep=1), box((0.1, 0.1, 0.2, 0.2)), box(occ=1)], "occluded"),
    ],
)
def test_stratum_priority(boxes, expected):
    assert r0a.stratum(boxes)[0] == expected


def test_negative_sampling_is_deterministic_and_order_free():
    ids = [f"{i:016x}" for i in range(2000)]
    a = r0a.sample_negatives(ids)
    assert a == r0a.sample_negatives(list(reversed(ids)))
    assert len(a) == r0a.NEG_SAMPLE and len(set(a)) == r0a.NEG_SAMPLE
    assert r0a.sample_negatives(ids[:10]) == sorted(ids[:10])


def test_flickr_id():
    url = "https://c5.staticflickr.com/1/125/321313101_baa21bff91_o.jpg"
    assert r0a.flickr_id(url) == "321313101"


def test_camera_equivalent_only_downscales():
    big = np.zeros((3000, 4000, 3), np.uint8)
    out = r0a.camera_equivalent(big)
    assert abs(out.shape[0] * out.shape[1] - r0a.CAMERA_PIXELS) < 2000
    assert out.shape[1] / out.shape[0] == pytest.approx(4 / 3, rel=0.01)
    small = np.zeros((300, 400, 3), np.uint8)
    assert r0a.camera_equivalent(small) is small


def test_occlusion_band_covers_the_requested_fraction_from_one_side():
    rgb = np.zeros((100, 200, 3), np.uint8)
    out = r0a.occlude(rgb, [0.25, 0.2, 0.75, 0.8], 0.5, "left")
    band = (out == r0a.GRAY).all(axis=2)
    assert band[20:80, 50:100].all() and not band[:, 100:].any() and not band[:20].any()
    out = r0a.occlude(rgb, [0.25, 0.2, 0.75, 0.8], 0.25, "right")
    band = (out == r0a.GRAY).all(axis=2)
    assert band[20:80, 125:150].all() and not band[:, :125].any()
    assert r0a.occlusion_side("abc") in ("left", "right")


def test_wilson_interval():
    lo, hi = r0a.wilson(45, 50)
    assert 0.78 < lo < 0.80 and 0.95 < hi < 0.97
    assert r0a.wilson(0, 0) is None
    assert r0a.wilson(0, 100)[0] == 0.0


def test_image_outcome_localized_hit_needs_the_threshold_and_overlap():
    row = {"boxes": json.dumps([[0.1, 0.1, 0.5, 0.5]])}
    rec = {
        "width": 100,
        "height": 100,
        "detections": [[0.9, 60, 60, 90, 90], [0.6, 10, 10, 50, 50]],
    }
    o = r0a.image_outcome(row, rec)
    assert o["c_max"] == 0.9 and not o["localized_hit"]  # confident, but elsewhere
    rec["detections"].append([0.75, 12, 12, 48, 50])
    assert r0a.image_outcome(row, rec)["localized_hit"]


def test_ap50_perfect_and_empty():
    rows = [
        {"image_id": "a", "boxes": json.dumps([[0.1, 0.1, 0.5, 0.5]])},
        {"image_id": "b", "boxes": "[]"},
    ]
    recs = {
        "a": {"width": 10, "height": 10, "detections": [[0.9, 1, 1, 5, 5]]},
        "b": {"width": 10, "height": 10, "detections": [[0.1, 1, 1, 2, 2]]},
    }
    assert r0a.ap50(rows, recs) == pytest.approx(1.0)
    assert r0a.ap50(rows[1:], recs) is None


def test_criteria_follow_decision_020():
    def r(k, n):
        return r0a.rate(k, n)

    s = {
        "camera": {
            "positives": {"clear": {"localized_recall_at_present": r(90, 100)}},
            "negatives": {"false_present": r(1, 100), "absent_blocked": r(11, 100)},
        }
    }
    c = r0a.criteria(s)
    assert c["A1_clear_localized_recall"]["pass"] and c["A2_false_present"]["pass"]
    assert not c["A3_absent_blocked"]["absent_usable"]


def test_select_from_metadata_only(tmp_path):
    h = r0a.HYDRANT
    lab = "ImageID,Source,LabelName,Confidence\n"
    bbox = (
        "ImageID,Source,LabelName,Confidence,XMin,XMax,YMin,YMax,"
        "IsOccluded,IsTruncated,IsGroupOf,IsDepiction,IsInside\n"
    )
    img = (
        "ImageID,Subset,OriginalURL,OriginalLandingURL,License,AuthorProfileURL,Author,Title,"
        "OriginalSize,OriginalMD5,Thumbnail300KURL,Rotation\n"
    )

    def imgrow(i, rot="0.0", photo="1"):
        return f"{i},x,https://f.com/a/{photo}_s_o.jpg,,lic,,auth,,1,m,,{rot}\n"

    files = {
        "validation": (
            lab + f"v1,h,{h},1\nv2,h,{h},0\n",
            bbox + f"v1,x,{h},1,0.1,0.6,0.1,0.7,0,0,0,0,0\n",
            img + imgrow("v1") + imgrow("v2"),
        ),
        "test": (
            lab + f"t1,h,{h},1\nt2,h,{h},1\nt3,h,{h},0\nt4,h,{h},1\n",
            bbox + f"t1,x,{h},1,0.1,0.2,0.1,0.2,0,0,0,0,0\nt2,x,{h},1,0.1,0.6,0.1,0.7,1,0,0,0,0\n",
            img + imgrow("t1") + imgrow("t2", rot="90.0") + imgrow("t3", photo="99"),
        ),
        "train": (lab, bbox, img),
    }
    names = {
        "validation": (
            "validation-annotations-human-imagelabels-boxable.csv",
            "validation-annotations-bbox.csv",
            "validation-images-with-rotation.csv",
        ),
        "test": (
            "test-annotations-human-imagelabels-boxable.csv",
            "test-annotations-bbox.csv",
            "test-images-with-rotation.csv",
        ),
        "train": (
            "train-imagelabels-hydrant.csv",
            "train-bbox-hydrant.csv",
            "train-images-hydrant.csv",
        ),
    }
    for subset, contents in files.items():
        for name, text in zip(names[subset], contents, strict=True):
            (tmp_path / name).write_text(text)
    manifests, audit = r0a.select(tmp_path, coco_flickr={"99"})
    dev = {r["image_id"]: r for r in manifests["dev"]}
    assert dev["v1"]["stratum"] == "clear" and dev["v2"]["label"] == "neg"
    formal = {r["image_id"]: r for r in manifests["formal"]}
    assert set(formal) == {"t1"} and formal["t1"]["stratum"] == "small"
    ex = audit["formal"]["excluded"]
    assert ex["pos: rotation 90.0"] == 1  # t2
    assert ex["neg: also in COCO 2017"] == 1  # t3
    assert ex["pos: verified but no box (test)"] == 1  # t4
