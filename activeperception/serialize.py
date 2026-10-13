"""JSON (de)serialisation for frozen episode sets and run records."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from .types import (
    Box,
    CameraModel,
    Decision,
    Detection,
    EpisodeGroundTruth,
    EpisodeRecord,
    EpisodeSpec,
    GroundTruthState,
    InspectionZone,
    Observation,
    Pose,
    SceneLayout,
    Split,
    Viewpoint,
)


def to_dict(obj: Any) -> Any:
    return dataclasses.asdict(obj)


def _pose(d: dict) -> Pose:
    return Pose(**d)


def _viewpoint(d: dict) -> Viewpoint:
    return Viewpoint(
        id=d["id"],
        pose=_pose(d["pose"]),
        azimuth=d["azimuth"],
        radius=d["radius"],
        height=d["height"],
    )


def spec_from_dict(d: dict) -> EpisodeSpec:
    lay = d["layout"]
    return EpisodeSpec(
        episode_id=d["episode_id"],
        namespace=d["namespace"],
        scene_group=d["scene_group"],
        variant=d["variant"],
        seed=d["seed"],
        split=Split(d["split"]),
        generator_version=d["generator_version"],
        zone=InspectionZone(**d["zone"]),
        camera=CameraModel(**d["camera"]),
        initial_viewpoint=_viewpoint(d["initial_viewpoint"]),
        candidate_viewpoints=tuple(_viewpoint(v) for v in d["candidate_viewpoints"]),
        layout=SceneLayout(
            object_present=lay["object_present"],
            object_pose=_pose(lay["object_pose"]) if lay["object_pose"] is not None else None,
            object_model=lay["object_model"],
            object_radius=lay["object_radius"],
            object_height=lay["object_height"],
            occluders=tuple(Box(**b) for b in lay["occluders"]),
        ),
    )


def gt_from_dict(d: dict) -> EpisodeGroundTruth:
    return EpisodeGroundTruth(
        episode_id=d["episode_id"],
        object_present=d["object_present"],
        state=GroundTruthState(d["state"]),
        revealable=d["revealable"],
        visibility_initial=d["visibility_initial"],
        visibility_by_viewpoint={int(k): float(v) for k, v in d["visibility_by_viewpoint"].items()},
        zone_visible_by_viewpoint={
            int(k): float(v) for k, v in d["zone_visible_by_viewpoint"].items()
        },
        labeling_version=d["labeling_version"],
    )


def observation_from_dict(d: dict) -> Observation:
    return Observation(
        viewpoint_id=d["viewpoint_id"],
        viewpoint=_viewpoint(d["viewpoint"]),
        detections=tuple(
            Detection(
                confidence=x["confidence"],
                bbox=tuple(x["bbox"]),
                area_frac=x["area_frac"],
                center_uv=tuple(x["center_uv"]),
            )
            for x in d["detections"]
        ),
        zone_visible_fraction=d["zone_visible_fraction"],
        timestamp=d["timestamp"],
        image_ref=d.get("image_ref"),
        meta=d.get("meta", {}),
    )


def record_from_dict(d: dict) -> EpisodeRecord:
    return EpisodeRecord(
        episode_id=d["episode_id"],
        policy=d["policy"],
        budget=d["budget"],
        run_seed=d["run_seed"],
        viewpoint_sequence=tuple(d["viewpoint_sequence"]),
        observations=tuple(observation_from_dict(o) for o in d["observations"]),
        decision=Decision(d["decision"]),
        confidence=d["confidence"],
        features=d["features"],
    )


def save_episode_set(
    path: str | Path,
    specs: list[EpisodeSpec],
    ground_truth: dict[str, EpisodeGroundTruth],
    world_name: str,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "format": "episode-set-v1",
        "world": world_name,
        "generator_version": specs[0].generator_version if specs else None,
        "n_episodes": len(specs),
        "episodes": [
            {"spec": to_dict(s), "ground_truth": to_dict(ground_truth[s.episode_id])} for s in specs
        ],
    }
    if extra:
        payload.update(extra)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=1, sort_keys=True))


def load_episode_set(
    path: str | Path,
) -> tuple[list[EpisodeSpec], dict[str, EpisodeGroundTruth], dict]:
    payload = json.loads(Path(path).read_text())
    specs = [spec_from_dict(e["spec"]) for e in payload["episodes"]]
    gts = {e["spec"]["episode_id"]: gt_from_dict(e["ground_truth"]) for e in payload["episodes"]}
    meta = {k: v for k, v in payload.items() if k != "episodes"}
    return specs, gts, meta


def write_jsonl(path: str | Path, rows: list[Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(
                json.dumps(to_dict(r) if dataclasses.is_dataclass(r) else r, sort_keys=True) + "\n"
            )


def read_jsonl(path: str | Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]
