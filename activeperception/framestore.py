"""Frame store: one compressed npz per episode with every viewpoint rendered once.

Format ``render-v1`` (decision 007), written by ``sim.render`` inside the container and
by ``sim.raycast.write_proxy_frames`` in tests:

* ``vp_ids`` (V,) int16, initial viewpoint first; ``poses`` (V, 5) x, y, z, yaw, pitch
* ``rgb`` (V, H, W, 3) uint8; ``depth_mm`` (V, H, W) uint16; ``labels`` (V, H, W) uint8
* ``stamps_ns`` / ``t_ref_ns`` (V,) int64
* object present only: ``labels_clear`` (+ ``stamps_clear_ns``, ``t_ref_clear_ns``)
* ``meta``: JSON string (episode id, spec digest, versions, ...)

Pure numpy so the container can import it. Labels are only exposed through
``EpisodeFrames.labels`` / ``labels_clear``; deployable code paths never call them.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

import numpy as np

FRAME_FORMAT = "render-v1"
DEPTH_NO_RETURN = 65535


def encode_depth_mm(depth: np.ndarray) -> np.ndarray:
    """metres float -> uint16 millimetres; +inf / beyond range -> 65535, NaN / <= 0 -> 0."""
    with np.errstate(invalid="ignore"):
        out = np.where(np.isfinite(depth), np.round(depth * 1000.0), float(DEPTH_NO_RETURN))
        out = np.where(np.isnan(depth) | (depth <= 0), 0.0, out)
    return np.clip(out, 0, DEPTH_NO_RETURN).astype(np.uint16)


def decode_depth_mm(depth_mm: np.ndarray) -> np.ndarray:
    out = depth_mm.astype(np.float32) / 1000.0
    out[depth_mm == DEPTH_NO_RETURN] = np.inf
    out[depth_mm == 0] = np.nan
    return out


def write_episode_frames(path: Path, arrays: dict[str, np.ndarray], meta: dict) -> None:
    """Atomically write one episode (``arrays`` keys as in the module docstring)."""
    required = {"vp_ids", "poses", "rgb", "depth_mm", "labels", "stamps_ns", "t_ref_ns"}
    missing = required - set(arrays)
    if missing:
        raise ValueError(f"missing frame arrays {sorted(missing)}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.tmp.npz")
    np.savez_compressed(tmp, **arrays, meta=np.array(json.dumps({"format": FRAME_FORMAT, **meta})))
    tmp.replace(path)


class EpisodeFrames:
    def __init__(self, path: Path):
        self.path = Path(path)
        npz = np.load(self.path)
        self._arrays = {k: npz[k] for k in npz.files}
        self.meta = json.loads(str(self._arrays.pop("meta")))
        if self.meta.get("format", FRAME_FORMAT) != FRAME_FORMAT:
            raise ValueError(f"{path}: unsupported frame format {self.meta.get('format')}")
        self._index = {int(v): i for i, v in enumerate(self._arrays["vp_ids"])}
        self._depth: dict[int, np.ndarray] = {}

    @property
    def episode_id(self) -> str:
        return self.meta["episode_id"]

    @property
    def viewpoint_ids(self) -> list[int]:
        return list(self._index)

    def _i(self, vp_id: int) -> int:
        try:
            return self._index[int(vp_id)]
        except KeyError:
            raise KeyError(f"{self.episode_id}: viewpoint {vp_id} not rendered") from None

    def pose(self, vp_id: int) -> np.ndarray:
        return self._arrays["poses"][self._i(vp_id)]

    def rgb(self, vp_id: int) -> np.ndarray:
        return self._arrays["rgb"][self._i(vp_id)]

    def depth(self, vp_id: int) -> np.ndarray:
        i = self._i(vp_id)
        if i not in self._depth:
            self._depth[i] = decode_depth_mm(self._arrays["depth_mm"][i])
        return self._depth[i]

    def stamp_s(self, vp_id: int) -> float:
        return float(self._arrays["stamps_ns"][self._i(vp_id)]) / 1e9

    # ---- offline GT only (grader / oracle / detector evaluation) ----------
    def labels(self, vp_id: int) -> np.ndarray:
        return self._arrays["labels"][self._i(vp_id)]

    def labels_clear(self, vp_id: int) -> np.ndarray | None:
        arr = self._arrays.get("labels_clear")
        return None if arr is None else arr[self._i(vp_id)]


class FrameStore:
    """Directory of ``<episode_id>.npz`` files with a small LRU of decoded episodes."""

    def __init__(self, root: str | Path, cache_size: int = 8):
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError(f"frame store {self.root} does not exist")
        self._cache: OrderedDict[str, EpisodeFrames] = OrderedDict()
        self._cache_size = cache_size

    def path(self, episode_id: str) -> Path:
        return self.root / f"{episode_id}.npz"

    def has(self, episode_id: str) -> bool:
        return self.path(episode_id).exists()

    def episode_ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.npz") if not p.name.startswith("."))

    def episode(self, episode_id: str) -> EpisodeFrames:
        if episode_id in self._cache:
            self._cache.move_to_end(episode_id)
            return self._cache[episode_id]
        frames = EpisodeFrames(self.path(episode_id))
        self._cache[episode_id] = frames
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return frames
