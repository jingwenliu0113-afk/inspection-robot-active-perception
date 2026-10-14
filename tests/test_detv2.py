"""detector-v2 data / training / evaluation helpers (decision 027). No model is trained here."""

import json
from pathlib import Path

import numpy as np
import pytest

from activeperception import r0a
from activeperception.detv2 import data, evaluate, train

SPLITS = {k: r0a.read_csv(Path(f"data/detv2/{k}.csv")) for k in ("train", "dev", "test")}


def test_splits_are_disjoint_and_keep_used_data_out():
    data.check_disjoint(SPLITS)
    used = {r["image_id"] for r in r0a.read_csv(Path("data/r0a/manifest-formal.csv"))}
    used |= {r["image_id"] for r in r0a.read_csv(Path("data/r0a/manifest-dev.csv"))}
    for rows in SPLITS.values():
        assert not used & {r["image_id"] for r in rows}  # R0a never reused


def test_test_split_is_the_v3_reserve_plus_evaluation_only_coco():
    reserve = {r["image_id"] for r in r0a.read_csv(Path("data/v3/realimg-reserve.csv"))}
    test = SPLITS["test"]
    oi = {r["image_id"] for r in test if r["source"].startswith("oi-")}
    assert oi == reserve
    coco = [r for r in test if r["source"].startswith("coco")]
    assert coco and all(r["license"] not in data.COCO_LICENCES.values() for r in coco)
    # nothing trained on may be NC / ND
    for r in SPLITS["train"] + SPLITS["dev"]:
        assert "-nc" not in r["license"] and "-nd" not in r["license"]


def test_v3_development_negatives_split_between_train_and_dev():
    dev_negs = {
        r["image_id"] for r in r0a.read_csv(Path("data/v3/realimg-dev.csv")) if r["label"] == "neg"
    }
    tr = {r["image_id"] for r in SPLITS["train"] if r["kind"] == "verified-negative"}
    dv = {r["image_id"] for r in SPLITS["dev"] if r["kind"] == "verified-negative"}
    assert tr | dv == dev_negs and not tr & dv
    assert abs(len(dv) / len(dev_negs) - data.DEV_FRACTION) < 0.01


def test_boxes_to_pixels():
    oi = {"source": "oi-train", "boxes": json.dumps([[0.1, 0.2, 0.5, 0.9]])}
    assert train.boxes_px(oi, 0.5, 640, 480)[0].tolist() == pytest.approx([64, 96, 320, 432])
    coco = {"source": "coco-train2017", "boxes": json.dumps([[100, 50, 300, 250]])}
    assert train.boxes_px(coco, 0.5, 640, 480).tolist() == [[50, 25, 150, 125]]
    neg = {"source": "oi-test", "boxes": "[]"}
    assert train.boxes_px(neg, 1.0, 640, 480).shape == (0, 4)


def test_batches_keep_the_positive_share():
    rows = [{"label": "pos", "i": i} for i in range(10)] + [
        {"label": "neg", "i": i} for i in range(90)
    ]
    cfg = train.CONFIGS["base"]
    picked = [r for b in train.batches(rows, cfg, np.random.default_rng(0)) for r in b]
    assert sum(r["label"] == "neg" for r in picked) == 90  # every negative once
    assert sum(r["label"] == "pos" for r in picked) == 90  # positives re-drawn to 50 %


def test_cli_never_touches_the_test_manifest():
    with pytest.raises(SystemExit):
        data.main(["download", "--manifest", "data/detv2/test.csv"])
    with pytest.raises(SystemExit):
        train.main(["--train", "data/detv2/test.csv", "--out", "/nonexistent"])
    with pytest.raises(SystemExit):
        evaluate.main(["detect", "--manifest", "data/detv2/test.csv", "--out", "/nonexistent"])


def test_real_metrics_and_pairing():
    pos = {"image_id": "p", "source": "coco-val2017", "label": "pos", "kind": "boxed"}
    neg = {"image_id": "n", "source": "oi-test", "label": "neg", "kind": "verified-negative"}
    rows = [
        {**pos, "category": "hydrant", "boxes": json.dumps([[0, 0, 100, 200]])},
        {**neg, "category": "negative", "boxes": "[]"},
    ]
    rec = {"scale": 1.0, "width": 640, "height": 480}
    v1 = {
        "coco-val2017:p": {**rec, "detections": [[0.9, 300, 300, 400, 400]]},  # wrong place
        "oi-test:n": {**rec, "detections": [[0.8, 0, 0, 10, 10]]},  # false present
    }
    v2 = {
        "coco-val2017:p": {**rec, "detections": [[0.9, 0, 0, 100, 190]]},
        "oi-test:n": {**rec, "detections": [[0.01, 0, 0, 10, 10]]},
    }
    a, b = evaluate.real(rows, v1), evaluate.real(rows, v2)
    assert a["pos:boxed"]["found"]["k"] == 0 and b["pos:boxed"]["found"]["k"] == 1
    assert a["neg:verified"]["present"]["k"] == 1 and b["neg:verified"]["present"]["k"] == 0
    assert b["neg:verified"]["absent_blocked"]["k"] == 0
    p = evaluate.paired_real(rows, v1, v2)
    assert p["pos:boxed"]["fixed"] == 1 and p["neg:verified"]["fixed"] == 1
