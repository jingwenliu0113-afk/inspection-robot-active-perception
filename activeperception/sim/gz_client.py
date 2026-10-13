"""gz-transport client for the inspection world. Runs INSIDE the simulation container.

Teleport protocol (decision 007):

1. ``/world/<world>/set_pose/blocking`` moves ``inspector_cam``.
2. ``t_ref`` = newest header stamp (sim time) among the frames already received
   when the service returns. The pose is in effect from the next sim iteration.
3. For every sensor, accept the first frame whose stamp is later than
   ``t_ref + settle`` (default 2.5 sensor periods at 10 Hz), so the frame was
   rendered after the pose took effect.

The world clock is deliberately NOT subscribed: it is published every physics step
(~250 Hz) and, with the Python bindings, starves service replies (requests time out)
and crashes the interpreter at exit. Verified in the M2 smoke test (2026-10-13).

Only numpy and the gz Python bindings are needed (no ROS, no host packages).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

from ..geometry import pose_quaternion
from ..types import Pose
from .sdf import CAMERA_MODEL, DEPTH_TOPIC, RGB_TOPIC, SEG_TOPIC, WORLD_NAME

LABELS_TOPIC = SEG_TOPIC + "/labels_map"
FRAME_KEYS = ("rgb", "depth", "labels")


class GzClientError(RuntimeError):
    pass


@dataclass
class Frame:
    stamp_ns: int
    array: np.ndarray


def _stamp_ns(msg) -> int:
    return int(msg.header.stamp.sec) * 1_000_000_000 + int(msg.header.stamp.nsec)


def decode_image(msg) -> np.ndarray:
    """gz.msgs.Image -> numpy (H, W) or (H, W, C) honouring ``step`` padding."""
    from gz.msgs10 import image_pb2 as im  # PixelFormatType values live at module level

    fmt = msg.pixel_format_type
    h, w, step = msg.height, msg.width, msg.step
    if fmt in (im.RGB_INT8, im.BGR_INT8):
        dtype, ch = np.uint8, 3
    elif fmt in (im.RGBA_INT8, im.BGRA_INT8):
        dtype, ch = np.uint8, 4
    elif fmt == im.L_INT8:
        dtype, ch = np.uint8, 1
    elif fmt == im.L_INT16:
        dtype, ch = np.uint16, 1
    elif fmt == im.R_FLOAT32:
        dtype, ch = np.float32, 1
    else:
        raise GzClientError(f"unsupported pixel format {im.PixelFormatType.Name(fmt)}")
    itemsize = np.dtype(dtype).itemsize
    raw = np.frombuffer(msg.data, dtype=np.uint8).reshape(h, step)[:, : w * ch * itemsize]
    arr = np.ascontiguousarray(raw).view(dtype)
    arr = arr.reshape(h, w, ch) if ch > 1 else arr.reshape(h, w)
    if fmt in (im.BGR_INT8, im.BGRA_INT8):
        arr = arr[..., [2, 1, 0] + ([3] if ch == 4 else [])]
    return arr


class GzClient:
    def __init__(
        self,
        world: str = WORLD_NAME,
        camera_model: str = CAMERA_MODEL,
        topics: dict[str, str] | None = None,
    ):
        from gz.msgs10.image_pb2 import Image
        from gz.transport13 import Node

        self.world = world
        self.camera_model = camera_model
        self.topics = topics or {"rgb": RGB_TOPIC, "depth": DEPTH_TOPIC, "labels": LABELS_TOPIC}
        self._cv = threading.Condition()
        self._latest: dict[str, object] = {}
        self._node = Node()
        for key, topic in self.topics.items():
            if not self._node.subscribe(Image, topic, self._image_cb(key)):
                raise GzClientError(f"cannot subscribe to {topic}")

    def _image_cb(self, key: str):
        def cb(msg) -> None:
            with self._cv:
                self._latest[key] = msg
                self._cv.notify_all()

        return cb

    def reset(self) -> None:
        """Forget received frames (call after (re)starting a server: sim time restarts)."""
        with self._cv:
            self._latest.clear()

    def latest_stamp_ns(self) -> int:
        """Newest header stamp among the frames received so far (-1 if none)."""
        with self._cv:
            return max((_stamp_ns(m) for m in self._latest.values()), default=-1)

    def wait_ready(self, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        with self._cv:
            while not set(self.topics) <= set(self._latest):
                left = deadline - time.monotonic()
                if left <= 0:
                    missing = sorted(set(self.topics) - set(self._latest))
                    raise GzClientError(f"sensors not ready, missing {missing}")
                self._cv.wait(left)

    def set_pose(self, pose: Pose, model: str | None = None, timeout_ms: int = 5000) -> None:
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10.pose_pb2 import Pose as PoseMsg

        req = PoseMsg()
        req.name = model or self.camera_model
        req.position.x, req.position.y, req.position.z = pose.x, pose.y, pose.z
        w, x, y, z = pose_quaternion(pose.yaw, pose.pitch)
        req.orientation.w, req.orientation.x = w, x
        req.orientation.y, req.orientation.z = y, z
        self._request(f"/world/{self.world}/set_pose/blocking", req, PoseMsg, Boolean, timeout_ms)

    def remove_model(self, name: str, timeout_ms: int = 5000) -> None:
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10.entity_pb2 import Entity

        req = Entity()
        req.name = name
        req.type = Entity.MODEL
        self._request(f"/world/{self.world}/remove/blocking", req, Entity, Boolean, timeout_ms)

    def _request(self, service, req, req_type, rep_type, timeout_ms, discovery_s=20.0) -> None:
        """Call a Boolean-reply service; retry while gz-transport is still discovering it."""
        deadline = time.monotonic() + discovery_s
        while True:
            ok, rep = self._node.request(service, req, req_type, rep_type, timeout_ms)
            if ok and rep.data:
                return
            if ok or time.monotonic() > deadline:
                raise GzClientError(f"{service} failed (reached={ok}) for {req}")
            time.sleep(0.2)

    def grab(self, after_ns: int, timeout: float = 30.0) -> dict[str, Frame]:
        """First frame per sensor with header stamp strictly later than ``after_ns``."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                fresh = {
                    k: m
                    for k, m in self._latest.items()
                    if k in self.topics and _stamp_ns(m) > after_ns
                }
                if len(fresh) == len(self.topics):
                    return {k: Frame(_stamp_ns(m), decode_image(m)) for k, m in fresh.items()}
                left = deadline - time.monotonic()
                if left <= 0:
                    stale = sorted(set(self.topics) - set(fresh))
                    raise GzClientError(f"no fresh frame after {after_ns} ns for {stale}")
                self._cv.wait(left)

    def teleport_and_grab(
        self, pose: Pose, settle_ns: int = 250_000_000
    ) -> tuple[int, dict[str, Frame]]:
        """Teleport the camera; return (t_ref, frames rendered after t_ref + settle)."""
        self.set_pose(pose)
        t_ref = self.latest_stamp_ns()
        return t_ref, self.grab(t_ref + settle_ns)
