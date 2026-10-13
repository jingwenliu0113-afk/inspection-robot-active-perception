"""B0 analysis (decision 015 section 5). Runs on the Mac over ``runs/nav-b0``.

    uv run --extra detectors python -m activeperception.nav.b0_analysis \\
        --runs runs/nav-b0 --out results/nav-b0

Deployable vs scoring is kept explicit:

- ``observation`` builds the decision input from the onboard depth, the detector output and
  the camera pose derived from the **AMCL estimate** (``deployable_camera_pose``). It has no
  ground-truth parameter.
- Ground truth (``/gt/odom`` base pose, semantic labels, object presence) is used only to
  score: navigation success, localisation error, depth check, collisions, wrong answers.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
from pathlib import Path

import numpy as np

from .. import frozen_v2
from ..framestore import decode_depth_mm
from ..sensing import (
    location_visibility_from_depth,
    obstacle_cells_from_depth,
    zone_visible_fraction_from_depth,
)
from ..sim.raycast import render as raycast
from ..sim.sdf import LABEL_GROUND, LABEL_OBJECT, LABEL_PILLAR
from ..types import Decision, Detection, EpisodeSpec, Observation, Pose, Viewpoint
from . import scene
from .robot import BASE_REST_Z, CAMERA_ABOVE_BASE
from .world import LABEL_WALL

ROBOT_RADIUS_M = 0.175  # TurtleBot 4 (Create 3 base 0.171 m + bumper)
ARRIVAL_XY_M = 0.10  # C3
ARRIVAL_YAW = 0.10
LOC_XY_P95_M = 0.10  # C4
LOC_YAW_P95 = 0.05
RTF_MIN = 0.5  # C2
NAV_SUCCESS_MIN = 0.90
FRESH_MIN = 0.99  # C5 (a)
DEPTH_MEDIAN_M = 0.01  # C5 (b)
DEPTH_FRAMES_MIN = 0.95
STATIC_LABELS = (LABEL_GROUND, LABEL_PILLAR, LABEL_WALL)


def _rot(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = (f(a) for a in (roll, pitch, yaw) for f in (math.cos, math.sin))
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1.0]])
    ry = np.array([[cp, 0, sp], [0, 1.0, 0], [-sp, 0, cp]])
    rx = np.array([[1.0, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return rz @ ry @ rx


def camera_pose(
    x: float, y: float, yaw: float, z: float = BASE_REST_Z, roll: float = 0.0, pitch: float = 0.0
) -> tuple[Pose, float]:
    """Mast camera pose from a base pose; returns (pose, residual roll about the optical axis).

    ``Pose`` has no roll; with a level base the residual is 0.
    """
    r_base = _rot(roll, pitch, yaw)
    pos = np.array([x, y, z]) + r_base @ np.array([0.0, 0.0, CAMERA_ABOVE_BASE])
    r_cam = r_base @ _rot(0.0, scene.MAST_PITCH, 0.0)
    f, left = r_cam @ np.array([1.0, 0, 0]), r_cam @ np.array([0, 1.0, 0])
    cam_yaw = math.atan2(f[1], f[0])
    cam_pitch = -math.asin(max(-1.0, min(1.0, f[2])))
    level_left = np.array([-math.sin(cam_yaw), math.cos(cam_yaw), 0.0])
    resid = math.atan2(
        float(np.dot(np.cross(level_left, left), f)), float(np.dot(level_left, left))
    )
    return Pose(float(pos[0]), float(pos[1]), float(pos[2]), cam_yaw, cam_pitch), resid


def deployable_camera_pose(estimate: dict) -> Pose:
    """Camera pose the robot believes it has: AMCL (x, y, yaw), level base at rest height."""
    return camera_pose(estimate["x"], estimate["y"], estimate["yaw"])[0]


def gt_camera_pose(gt: dict) -> tuple[Pose, float]:
    return camera_pose(gt["x"], gt["y"], gt["yaw"], gt["z"], gt["roll"], gt["pitch"])


def observation(
    spec: EpisodeSpec, index: int, depth: np.ndarray, dets: tuple[Detection, ...], pose: Pose
) -> Observation:
    """Decision input from deployable data only (no ground-truth argument)."""
    z = spec.zone
    vp = Viewpoint(
        id=index,
        pose=pose,
        azimuth=math.atan2(pose.y - z.cy, pose.x - z.cx) % (2 * math.pi),
        radius=math.hypot(pose.x - z.cx, pose.y - z.cy),
        height=pose.z,
    )
    return Observation(
        viewpoint_id=index,
        viewpoint=vp,
        detections=dets,
        zone_visible_fraction=zone_visible_fraction_from_depth(depth, spec.camera, pose, z),
        timestamp=float(index),
        obstacle_cells=obstacle_cells_from_depth(depth, spec.camera, pose, z),
        location_visibility=location_visibility_from_depth(depth, spec.camera, pose, z),
    )


def observation_d016(
    spec: EpisodeSpec, index: int, depth: np.ndarray, dets: tuple[Detection, ...], estimate: Pose
):
    """decision 016 decision input: refined pose + pose-robust see-through (deployable only)."""
    from .localize import deployable_pose_and_visibility, map_outlines

    pose, vis, ref = deployable_pose_and_visibility(
        depth, spec.camera, estimate, spec.zone, map_outlines(spec)
    )
    obs = dataclasses.replace(observation(spec, index, depth, dets, pose), location_visibility=vis)
    return obs, ref


def _angle(a: float) -> float:
    return abs((a + math.pi) % (2 * math.pi) - math.pi)


def box_distance(x: np.ndarray, y: np.ndarray, box) -> np.ndarray:
    dx = np.maximum(np.abs(x - box.cx) - box.sx / 2, 0.0)
    dy = np.maximum(np.abs(y - box.cy) - box.sy / 2, 0.0)
    return np.hypot(dx, dy)


def clearance(trace: np.ndarray, spec: EpisodeSpec) -> dict:
    """Scoring: closest approach of the robot body to pillars / walls / the zone (GT path)."""
    if len(trace) == 0:
        return {"obstacle_m": None, "zone_m": None}
    x, y = trace[:, 1], trace[:, 2]
    d = min(float(box_distance(x, y, b).min()) for b in (*spec.layout.occluders, *scene.walls()))
    z = spec.zone
    dz = float((np.hypot(x - z.cx, y - z.cy) - z.radius).min())
    return {"obstacle_m": d - ROBOT_RADIUS_M, "zone_m": dz - ROBOT_RADIUS_M}


def depth_check(spec: EpisodeSpec, depth: np.ndarray, labels: np.ndarray, pose: Pose) -> float:
    """Median |onboard - analytic ray-cast| over static-geometry pixels (scoring)."""
    ref, _ = raycast(spec.camera, pose, (*spec.layout.occluders, *scene.walls()), None)
    m = np.isin(labels, STATIC_LABELS) & np.isfinite(depth) & np.isfinite(ref)
    return float(np.median(np.abs(depth[m] - ref[m]))) if m.any() else float("nan")


def detect_all(runs: Path, episodes: list[str], cache_path: Path):
    from ..detector import FROZEN_DETECTOR
    from ..detector.cache import DetectionCache
    from ..detector.models import load_detector

    if cache_path.exists():
        return DetectionCache.load(cache_path)
    det = load_detector(FROZEN_DETECTOR, "models", "cpu")
    cache = DetectionCache(FROZEN_DETECTOR, {"device": det.device, "runs": str(runs)})
    for eid in episodes:
        rep = json.loads((runs / eid / "episode.json").read_text())
        for i, row in enumerate(rep["rows"]):
            rgb = np.load(runs / eid / row["file"])["rgb"]
            cache.put(eid, i, det.detect(rgb))  # [[conf, x1, y1, x2, y2], ...]
    cache.save(cache_path)
    return cache


def _q(v: list[float], q: float) -> float | None:
    return float(np.quantile(v, q)) if v else None


def analyze(runs: Path, cache) -> dict:
    specs = scene.specs_by_id()
    rule = frozen_v2.decision_rule()
    eps = sorted(p.parent.name for p in runs.glob("*/episode.json"))
    rtf, goals, cancels, loc_xy, loc_yaw, depth_err, depth_err_est = [], [], [], [], [], [], []
    fresh = total = 0
    pairs = {"n": 0, "wrong_definitive": [], "geometric_risk": [], "by_gt": {}}
    pairs16 = {"n": 0, "wrong_definitive": [], "geometric_risk": [], "by_gt": {}}
    refine_rows, per_episode16 = [], []
    per_episode, roll_max, detection_rows = [], 0.0, []
    for eid in eps:
        spec = specs[eid]
        rep = json.loads((runs / eid / "episode.json").read_text())
        obs_est, obs_gt, obs_d16 = [], [], []
        for i, row in enumerate(rep["rows"]):
            cap = np.load(runs / eid / row["file"])
            depth, labels = decode_depth_mm(cap["depth_mm"]), cap["labels"]
            dep, sc = row["deployable"], row["scoring"]
            total += 1
            stamps = dep["frame_stamps_s"].values()
            fresh += all(s > dep["capture_after_s"] for s in stamps)
            gt = sc["gt_base"]
            est = dep["estimate"]
            p_est = deployable_camera_pose(est)
            p_gt, resid = gt_camera_pose(gt)
            roll_max = max(roll_max, abs(resid))
            dets = cache.get(eid, i)
            obs_est.append(observation(spec, i, depth, dets, p_est))
            o16, ref = observation_d016(spec, i, depth, dets, p_est)
            obs_d16.append(o16)
            refine_rows.append(
                {
                    "ok": ref.ok,
                    "xy_m": math.hypot(
                        o16.viewpoint.pose.x - p_gt.x, o16.viewpoint.pose.y - p_gt.y
                    ),
                    "yaw": _angle(o16.viewpoint.pose.yaw - p_gt.yaw),
                    "eig": ref.min_eigenvalue,
                    "tag": row["tag"],
                }
            )
            obs_gt.append(observation(spec, i, depth, dets, p_gt))  # comparison only
            depth_err.append(depth_check(spec, depth, labels, p_gt))
            depth_err_est.append(depth_check(spec, depth, labels, p_est))
            n_obj = int((labels == LABEL_OBJECT).sum())
            detection_rows.append(
                {
                    "present": spec.layout.object_present,
                    "object_px": n_obj,
                    "max_conf": max((d.confidence for d in dets), default=0.0),
                }
            )
            e_xy = math.hypot(est["x"] - gt["x"], est["y"] - gt["y"])
            e_yaw = _angle(est["yaw"] - gt["yaw"])
            nav = row["nav"]
            if row["tag"] in ("initial", "goal"):
                loc_xy.append(e_xy)
                loc_yaw.append(e_yaw)
            if nav is None:
                continue
            if nav["rtf"] is not None:
                rtf.append(nav["rtf"])
            trace = np.load(runs / eid / nav["trace_file"])
            cl = clearance(trace, spec)
            g = nav["goal"]
            arr_xy = math.hypot(gt["x"] - g["x"], gt["y"] - g["y"])
            arr_yaw = _angle(gt["yaw"] - g["yaw"])
            item = {
                "episode": eid,
                "target": row["target"],
                "result": nav["result"],
                "arrival_xy_m": arr_xy,
                "arrival_yaw": arr_yaw,
                "sim_s": nav["sim_s"],
                "clearance": cl,
                "loc_xy_m": e_xy,
                "loc_yaw": e_yaw,
            }
            item["success"] = (
                nav["result"] == "SUCCEEDED" and arr_xy <= ARRIVAL_XY_M and arr_yaw <= ARRIVAL_YAW
            )
            (goals if row["tag"] == "goal" else cancels).append(item)
        # C6: initial view + any one later view, decided from deployable observations
        present = spec.layout.object_present
        for k in range(1, len(obs_est)):
            hist = [obs_est[0], obs_est[k]]
            out = rule.decide(spec.deployable(), hist)
            pairs["n"] += 1
            key = f"{'present' if present else 'absent'}->{out.decision.value}"
            pairs["by_gt"][key] = pairs["by_gt"].get(key, 0) + 1
            wrong = (out.decision == Decision.ABSENT and present) or (
                out.decision == Decision.PRESENT and not present
            )
            tag = rep["rows"][k]["tag"]
            if wrong:
                pairs["wrong_definitive"].append({"episode": eid, "capture": k, "tag": tag})
            if present and rule.cleared_fraction(hist) >= 1.0 - 1e-9:
                pairs["geometric_risk"].append({"episode": eid, "capture": k, "tag": tag})
        for k in range(1, len(obs_d16)):
            hist = [obs_d16[0], obs_d16[k]]
            out = rule.decide(spec.deployable(), hist)
            pairs16["n"] += 1
            key = f"{'present' if present else 'absent'}->{out.decision.value}"
            pairs16["by_gt"][key] = pairs16["by_gt"].get(key, 0) + 1
            if (out.decision == Decision.ABSENT and present) or (
                out.decision == Decision.PRESENT and not present
            ):
                pairs16["wrong_definitive"].append({"episode": eid, "capture": k})
            if present and rule.cleared_fraction(hist) >= 1.0 - 1e-9:
                pairs16["geometric_risk"].append({"episode": eid, "capture": k})
        u16 = rule.decide(spec.deployable(), obs_d16)
        per_episode16.append(
            {
                "episode": eid,
                "present": present,
                "all_views_decision": u16.decision.value,
                "cleared_fraction": rule.cleared_fraction(obs_d16),
                "all_views_geometric_risk": present
                and rule.cleared_fraction(obs_d16) >= 1.0 - 1e-9,
            }
        )
        union = rule.decide(spec.deployable(), obs_est)
        union_gt = rule.decide(spec.deployable(), obs_gt)
        # protection margin per view (scoring): locations NOT seen through, est vs GT pose
        margins = [
            {
                "capture": i,
                "uncleared_est": int(sum(v < 1 - 1e-9 for v in oe.location_visibility)),
                "uncleared_gt_pose": int(sum(v < 1 - 1e-9 for v in og.location_visibility)),
            }
            for i, (oe, og) in enumerate(zip(obs_est, obs_gt, strict=True))
        ]
        per_episode.append(
            {
                "episode": eid,
                "present": present,
                "all_views_decision": union.decision.value,
                "all_views_decision_with_gt_pose": union_gt.decision.value,
                "cleared_fraction_est": rule.cleared_fraction(obs_est),
                "cleared_fraction_gt_pose": rule.cleared_fraction(obs_gt),
                "all_views_geometric_risk": present
                and rule.cleared_fraction(obs_est) >= 1.0 - 1e-9,
                "view_margins": margins,
                "nav2_active_wall_s": rep["nav2_active_wall_s"],
                "total_wall_s": rep["total_wall_s"],
            }
        )
    n_goal = len(goals)
    succ = sum(g["success"] for g in goals)
    collisions = [g for g in goals + cancels if (g["clearance"]["obstacle_m"] or 0) < 0]
    zone_entries = [g for g in goals + cancels if (g["clearance"]["zone_m"] or 0) < 0]
    good_depth = [e for e in depth_err if e <= DEPTH_MEDIAN_M]
    c = {
        "C2_rtf_median": _q(rtf, 0.5),
        "C3_nav_success_rate": succ / n_goal if n_goal else None,
        "C3_collisions": len(collisions),
        "C4_loc_xy_p50_m": _q(loc_xy, 0.5),
        "C4_loc_xy_p95_m": _q(loc_xy, 0.95),
        "C4_loc_yaw_p50": _q(loc_yaw, 0.5),
        "C4_loc_yaw_p95": _q(loc_yaw, 0.95),
        "C5a_fresh_rate": fresh / total if total else None,
        "C5b_depth_ok_rate": len(good_depth) / len(depth_err) if depth_err else None,
        "C6_wrong_definitive": len(pairs["wrong_definitive"]),
        "C6_geometric_risk": len(pairs["geometric_risk"]),
    }
    verdict = {
        "C2": c["C2_rtf_median"] is not None and c["C2_rtf_median"] >= RTF_MIN,
        "C3": c["C3_nav_success_rate"] is not None
        and c["C3_nav_success_rate"] >= NAV_SUCCESS_MIN
        and c["C3_collisions"] == 0,
        "C4": c["C4_loc_xy_p95_m"] is not None
        and c["C4_loc_xy_p95_m"] <= LOC_XY_P95_M
        and c["C4_loc_yaw_p95"] <= LOC_YAW_P95,
        "C5": c["C5a_fresh_rate"] is not None
        and c["C5a_fresh_rate"] >= FRESH_MIN
        and c["C5b_depth_ok_rate"] >= DEPTH_FRAMES_MIN,
        "C6": c["C6_wrong_definitive"] == 0 and c["C6_geometric_risk"] == 0,
    }
    det_present = [r for r in detection_rows if r["present"]]
    return {
        "episodes": len(eps),
        "criteria": c,
        "verdict": verdict,
        "navigation": {
            "goals": n_goal,
            "succeeded": succ,
            "failures": [g for g in goals if not g["success"]],
            "arrival_xy_p50_m": _q([g["arrival_xy_m"] for g in goals], 0.5),
            "arrival_xy_p95_m": _q([g["arrival_xy_m"] for g in goals], 0.95),
            "arrival_yaw_p95": _q([g["arrival_yaw"] for g in goals], 0.95),
            "goal_sim_s_p50": _q([g["sim_s"] for g in goals], 0.5),
            "min_obstacle_clearance_m": min(
                (
                    g["clearance"]["obstacle_m"]
                    for g in goals + cancels
                    if g["clearance"]["obstacle_m"] is not None
                ),
                default=None,
            ),
            "zone_entries": len(zone_entries),
            "cancelled_stops": len(cancels),
            "cancel_loc_xy_p95_m": _q([g["loc_xy_m"] for g in cancels], 0.95),
            "cancel_loc_yaw_p95": _q([g["loc_yaw"] for g in cancels], 0.95),
        },
        "observation": {
            "captures": total,
            "depth_median_err_gt_pose_p50_m": _q(depth_err, 0.5),
            "depth_median_err_gt_pose_max_m": max(depth_err) if depth_err else None,
            "depth_median_err_est_pose_p50_m": _q(depth_err_est, 0.5),
            "depth_median_err_est_pose_p95_m": _q(depth_err_est, 0.95),
            "camera_residual_roll_max": roll_max,
            "detection_present_frames": len(det_present),
            "detected_at_0.7_when_object_px_ge_10k": _rate(
                [r["max_conf"] >= 0.7 for r in det_present if r["object_px"] >= 10_000]
            ),
            "detected_at_0.7_when_object_px_lt_5k": _rate(
                [r["max_conf"] >= 0.7 for r in det_present if r["object_px"] < 5_000]
            ),
            "absent_frames_max_conf": max(
                (r["max_conf"] for r in detection_rows if not r["present"]), default=None
            ),
        },
        "decision_016": {
            "refinement": {
                "captures": len(refine_rows),
                "ok": sum(r["ok"] for r in refine_rows),
                "ok_xy_p50_m": _q([r["xy_m"] for r in refine_rows if r["ok"]], 0.5),
                "ok_xy_p95_m": _q([r["xy_m"] for r in refine_rows if r["ok"]], 0.95),
                "ok_xy_max_m": max((r["xy_m"] for r in refine_rows if r["ok"]), default=None),
                "ok_yaw_p95": _q([r["yaw"] for r in refine_rows if r["ok"]], 0.95),
                "ok_yaw_max": max((r["yaw"] for r in refine_rows if r["ok"]), default=None),
                "degenerate_by_tag": {
                    t: sum(1 for r in refine_rows if not r["ok"] and r["tag"] == t)
                    for t in ("initial", "goal", "cancel")
                },
            },
            "R1_wrong_definitive": len(pairs16["wrong_definitive"]),
            "R1_geometric_risk": len(pairs16["geometric_risk"]),
            "R2_all_views_geometric_risk": sum(
                e["all_views_geometric_risk"] for e in per_episode16
            ),
            "pairs": pairs16,
            "per_episode": per_episode16,
        },
        "decisions": {
            "pairs": pairs,
            "all_views_geometric_risk_episodes": sum(
                e["all_views_geometric_risk"] for e in per_episode
            ),
            "per_episode": per_episode,
        },
    }


YAW_OFFSETS = (0.0, 0.01, 0.02, 0.03, 0.04, 0.06, 0.08)
LATERAL_OFFSETS_M = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10)


def pose_sensitivity(runs: Path) -> dict:
    """Descriptive (decision 015 C6 context): how large a camera-pose error makes a view of a
    PRESENT object look fully seen through. Starts from the ground-truth camera pose of every
    capture in a present episode and offsets yaw (both signs) or position (sideways, both
    signs) or along the viewing direction; a view is unsafe when all 64 locations count as
    seen through.
    """
    specs = scene.specs_by_id()
    views = []
    for p in sorted(runs.glob("*/episode.json")):
        spec = specs[p.parent.name]
        if not spec.layout.object_present:
            continue
        for row in json.loads(p.read_text())["rows"]:
            depth = decode_depth_mm(np.load(p.parent / row["file"])["depth_mm"])
            views.append((spec, depth, gt_camera_pose(row["scoring"]["gt_base"])[0]))

    def unsafe(spec, depth, pose) -> bool:
        vis = location_visibility_from_depth(depth, spec.camera, pose, spec.zone)
        return all(v >= 1 - 1e-9 for v in vis)

    out: dict = {"views": len(views), "yaw": {}, "lateral_m": {}, "forward_m": {}}
    for d in YAW_OFFSETS:
        n = sum(
            any(unsafe(sp, dp, dataclasses.replace(ps, yaw=ps.yaw + sg * d)) for sg in (1, -1))
            for sp, dp, ps in views
        )
        out["yaw"][str(d)] = n
    for d in LATERAL_OFFSETS_M:
        n = 0
        for sp, dp, ps in views:
            lx, ly = -math.sin(ps.yaw), math.cos(ps.yaw)
            n += any(
                unsafe(sp, dp, dataclasses.replace(ps, x=ps.x + sg * d * lx, y=ps.y + sg * d * ly))
                for sg in (1, -1)
            )
        out["lateral_m"][str(d)] = n
    for d in LATERAL_OFFSETS_M:  # along the horizontal viewing direction (estimate too close / far)
        n = 0
        for sp, dp, ps in views:
            fx, fy = math.cos(ps.yaw), math.sin(ps.yaw)
            n += any(
                unsafe(sp, dp, dataclasses.replace(ps, x=ps.x + sg * d * fx, y=ps.y + sg * d * fy))
                for sg in (1, -1)
            )
        out["forward_m"][str(d)] = n
    return out


def _rate(v: list[bool]) -> dict:
    return {"n": len(v), "rate": (sum(v) / len(v)) if v else None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.nav.b0_analysis")
    ap.add_argument("--runs", default="runs/nav-b0")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    runs = Path(args.runs)
    eps = sorted(p.parent.name for p in runs.glob("*/episode.json"))
    cache = detect_all(runs, eps, runs / "detector-v1.jsonl")
    report = analyze(runs, cache)
    report["pose_sensitivity"] = pose_sensitivity(runs)
    import subprocess

    report["git_commit"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    report["runs"] = str(runs)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "b0_report.json").write_text(json.dumps(report, indent=1, default=float) + "\n")
    print(json.dumps({"criteria": report["criteria"], "verdict": report["verdict"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
