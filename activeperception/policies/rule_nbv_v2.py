"""Rule-based next-best-view v2 (decision 011): target locations not yet seen through.

Deployable inputs only: the obstacle cells and viewpoints of visited views (depth), the
per-location see-through evidence they produced, detections and viewpoint geometry.

Known-space map (2D, 5 cm cells, 2.5 m around the zone): obstacle cells (>= 30 cm high)
from all visited depth images are *occupied*; a cell is *known free* when it lies inside
some visited camera's horizontal field of view and in front of the first obstacle along
its bearing; everything else is *unknown* (v1 implicitly treated it as free).

For each candidate, ``clear_gain`` predicts how many still-uncleared candidate locations its
lines of sight would see through: a sight line crossing an occupied cell counts 0, one
entirely through known-free cells counts 1, one crossing unknown cells counts ``p_unknown``.

score = w_gain * clear_gain + w_novelty * novelty + w_attraction * attraction
      + w_visibility * predicted_zone_visibility (the v1 feature)
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..decision import DecisionRuleV2Params
from ..geometry import angular_distance
from ..sensing import (
    LOCATION_SAMPLES,
    OBSTACLE_CELL_M,
    cleared_locations,
    location_grid,
    merge_obstacle_cells,
    predicted_zone_visibility,
)
from ..types import DeployableEpisode, Observation
from .base import unvisited_candidates

RULE_NBV_V2_VERSION = "rule-nbv-v2"
MAP_HALF_M = 2.5
MAP_RANGE_M = 4.5
MAP_STEP_M = 0.025
OCCUPIED_MIN_CM = 30
N_BEARINGS = 241
CAMERA_NEAR_FREE_M = 0.5


@dataclass(frozen=True)
class RuleNBVv2Params:
    w_gain: float = 1.0
    p_unknown: float = 0.25
    w_novelty: float = 0.25
    w_attraction: float = 0.0
    w_visibility: float = 0.0
    tau_weak: float = 0.15
    attraction_target: float = math.radians(45.0)
    attraction_sigma: float = math.radians(30.0)


class KnownMap:
    """Occupied / known-free 2D grid built from the visited views of one episode."""

    def __init__(self, episode: DeployableEpisode, history: Sequence[Observation]):
        zone = episode.zone
        self.cell = OBSTACLE_CELL_M
        self.n = int(round(2 * MAP_HALF_M / self.cell))
        self.ox, self.oy = zone.cx - MAP_HALF_M, zone.cy - MAP_HALF_M
        self.occ = np.zeros((self.n, self.n), dtype=bool)
        for (ix, iy), h in merge_obstacle_cells(o.obstacle_cells for o in history).items():
            if h >= OCCUPIED_MIN_CM:
                gi, gj = self._index((ix + 0.5) * self.cell, (iy + 0.5) * self.cell)
                if 0 <= gi < self.n and 0 <= gj < self.n:
                    self.occ[gi, gj] = True
        xs = self.ox + (np.arange(self.n) + 0.5) * self.cell
        ys = self.oy + (np.arange(self.n) + 0.5) * self.cell
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        self.free = np.zeros_like(self.occ)
        half = episode.camera.hfov / 2.0
        steps = np.arange(MAP_STEP_M, MAP_RANGE_M, MAP_STEP_M)
        for o in history:
            pose = o.viewpoint.pose
            bearings = pose.yaw + np.linspace(-half, half, N_BEARINGS)
            px = pose.x + steps[None, :] * np.cos(bearings)[:, None]
            py = pose.y + steps[None, :] * np.sin(bearings)[:, None]
            hit = self._lookup(self.occ, px, py)
            first = np.where(hit.any(axis=1), steps[np.argmax(hit, axis=1)], MAP_RANGE_M)
            dx, dy = gx - pose.x, gy - pose.y
            dist = np.hypot(dx, dy)
            rel = (np.arctan2(dy, dx) - pose.yaw + math.pi) % (2 * math.pi) - math.pi
            in_wedge = np.abs(rel) <= half
            b = np.clip(np.round((rel + half) / (2 * half) * (N_BEARINGS - 1)), 0, N_BEARINGS - 1)
            self.free |= in_wedge & (dist < first[b.astype(int)]) & (dist <= MAP_RANGE_M)
        self.free &= ~self.occ

    def _index(self, x, y):
        return (
            np.floor((np.asarray(x) - self.ox) / self.cell).astype(int),
            np.floor((np.asarray(y) - self.oy) / self.cell).astype(int),
        )

    def _lookup(self, grid: np.ndarray, x, y, outside: bool = False) -> np.ndarray:
        gi, gj = self._index(x, y)
        inside = (gi >= 0) & (gj >= 0) & (gi < self.n) & (gj < self.n)
        out = np.full(gi.shape, outside, dtype=bool)
        out[inside] = grid[gi[inside], gj[inside]]
        return out

    def sight_status(self, episode: DeployableEpisode, pose, targets: np.ndarray) -> np.ndarray:
        """Per 2D target: 0 = blocked, 1 = known clear, 2 = through unknown space.

        Known obstacles are checked along the whole sight line. Unknown space is only
        counted beyond ``CAMERA_NEAR_FREE_M`` from the candidate camera: a candidate
        viewpoint is a valid standing pose, so its immediate surroundings are taken as free
        (otherwise every candidate outside the visited views' wedges would look unknown).
        """
        zone = episode.zone
        t = np.arange(MAP_STEP_M, 1.0, MAP_STEP_M / 2.5)
        px = pose.x + t[None, :] * (targets[:, 0:1] - pose.x)
        py = pose.y + t[None, :] * (targets[:, 1:2] - pose.y)
        outside_zone = np.hypot(px - zone.cx, py - zone.cy) > zone.radius
        far = np.hypot(px - pose.x, py - pose.y) > CAMERA_NEAR_FREE_M
        blocked = (self._lookup(self.occ, px, py) & outside_zone).any(axis=1)
        known = (self._lookup(self.free, px, py) | ~outside_zone | ~far).all(axis=1)
        return np.where(blocked, 0, np.where(known, 1, 2))


class RuleNBVv2Policy:
    name = "rule"
    version = RULE_NBV_V2_VERSION

    def __init__(
        self,
        params: RuleNBVv2Params | None = None,
        decision_params: DecisionRuleV2Params | None = None,
        cache: dict | None = None,
        version: str | None = None,
    ):
        """``cache`` may be shared across instances running on the SAME world (sweeps)."""
        self.params = params or RuleNBVv2Params()
        self.dp = decision_params or DecisionRuleV2Params()
        self._shared = cache is not None
        self._cache: dict = {} if cache is None else cache
        self.version = version or RULE_NBV_V2_VERSION

    def reset(self, episode: DeployableEpisode, run_seed: int) -> None:
        if not self._shared:
            self._cache.clear()

    def _gain_counts(self, episode, history, vp, uncleared: np.ndarray) -> tuple[int, int]:
        """(known-clear, unknown) counts over the uncleared locations for candidate ``vp``."""
        visited = tuple(o.viewpoint_id for o in history)
        key = ("gain", episode.episode_id, visited, vp.id, self.dp.col_min)
        if key not in self._cache:
            mkey = ("map", episode.episode_id, visited)
            if mkey not in self._cache:
                self._cache[mkey] = KnownMap(episode, history)
            idx = np.flatnonzero(uncleared)
            if not len(idx):
                self._cache[key] = (0, 0)
            else:
                targets = location_grid(episode.zone)[idx]
                status = self._cache[mkey].sight_status(episode, vp.pose, targets)
                self._cache[key] = (int((status == 1).sum()), int((status == 2).sum()))
        return self._cache[key]

    def features(self, episode, history, vp, uncleared, height_map=None) -> dict[str, float]:
        p = self.params
        az = vp.azimuth
        n_clear, n_unknown = self._gain_counts(episode, history, vp, uncleared)
        feats = {
            "clear_gain": (n_clear + p.p_unknown * n_unknown) / LOCATION_SAMPLES,
            "novelty": min(angular_distance(az, o.viewpoint.azimuth) for o in history) / math.pi,
            "attraction": 0.0,
        }
        best = max(history, key=lambda o: o.max_confidence)
        if p.tau_weak <= best.max_confidence:
            d = angular_distance(az, best.viewpoint.azimuth) - p.attraction_target
            feats["attraction"] = math.exp(-(d * d) / (2.0 * p.attraction_sigma**2))
        if p.w_visibility:
            vkey = ("vis", episode.episode_id, tuple(o.viewpoint_id for o in history), vp.id)
            if vkey not in self._cache:
                hmap = (
                    height_map
                    if height_map is not None
                    else merge_obstacle_cells(o.obstacle_cells for o in history)
                )
                self._cache[vkey] = predicted_zone_visibility(
                    hmap, episode.camera, vp.pose, episode.zone
                )
            feats["predicted_visibility"] = self._cache[vkey]
        return feats

    def select_next(
        self, episode: DeployableEpisode, history: Sequence[Observation], remaining: int
    ) -> int | None:
        cands = unvisited_candidates(episode, history)
        if not cands:
            return None
        p = self.params
        uncleared = ~cleared_locations(history, self.dp.col_min)
        hmap = merge_obstacle_cells(o.obstacle_cells for o in history) if p.w_visibility else None
        scored = []
        for vp in cands:
            f = self.features(episode, history, vp, uncleared, hmap)
            s = (
                p.w_gain * f["clear_gain"]
                + p.w_novelty * f["novelty"]
                + p.w_attraction * f["attraction"]
                + p.w_visibility * f.get("predicted_visibility", 0.0)
            )
            scored.append((-s, vp.id))
        return sorted(scored)[0][1]
