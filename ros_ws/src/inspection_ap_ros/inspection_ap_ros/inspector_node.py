"""Live inspector: the shared decision rule and the four policies inside a ROS 2 graph.

    Gazebo (headless) --ros_gz_bridge--> /inspector/rgb, /inspector/depth (sensor_msgs/Image)
    inspector --/world/inspection/set_pose/blocking (ros_gz_interfaces/SetEntityPose)--> Gazebo

For every requested ``policy:budget`` the node calls the same ``harness.run_episode`` as the
replay experiment, with a live observation source: teleport over the bridge, wait for frames
rendered after the teleport (stamp > newest stamp at service return + settle), run
detector-v1 on the RGB frame and derive the zone visibility from the depth frame.

Publishes ``/inspection/detections`` (vision_msgs/Detection2DArray) per view and
``/inspection/decision`` (std_msgs/String, JSON) per run, and writes
``<out>/<episode_id>.json``. Core only: teleport, no Nav2 (SPEC §3).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from ros_gz_interfaces.msg import Entity
from ros_gz_interfaces.srv import SetEntityPose
from sensor_msgs.msg import Image
from std_msgs.msg import String
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose

from activeperception.decision import DecisionRule
from activeperception.detector import DETECTOR_VERSION, FROZEN_DETECTOR
from activeperception.detector.cache import make_detection
from activeperception.detector.models import TARGET_CLASS, load_detector
from activeperception.geometry import pose_quaternion
from activeperception.harness import run_episode
from activeperception.policies import (
    OracleNBVPolicy,
    RandomNBVPolicy,
    RuleNBVPolicy,
    SingleViewPolicy,
)
from activeperception.sensing import (
    location_visibility_from_depth,
    obstacle_cells_from_depth,
    zone_visible_fraction_from_depth,
)
from activeperception.serialize import load_episode_set
from activeperception.sim.sdf import CAMERA_MODEL
from activeperception.types import Observation


def stamp_ns(msg) -> int:
    return int(msg.header.stamp.sec) * 1_000_000_000 + int(msg.header.stamp.nanosec)


def image_to_numpy(msg: Image) -> np.ndarray:
    raw = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.step)
    if msg.encoding == "rgb8":
        return raw[:, : msg.width * 3].reshape(msg.height, msg.width, 3).copy()
    if msg.encoding == "32FC1":
        return raw[:, : msg.width * 4].copy().view(np.float32).reshape(msg.height, msg.width)
    raise ValueError(f"unsupported encoding {msg.encoding}")


def policies_for(config: str, gts):
    """(policy factories, decision rule) for a configuration; oracles only where offline-free."""
    if config == "v0":
        return {
            "single": SingleViewPolicy,
            "random": RandomNBVPolicy,
            "rule": RuleNBVPolicy,
            "oracle": lambda: OracleNBVPolicy(gts.__getitem__),
        }, DecisionRule()
    if config == "v1":
        from activeperception import frozen

        return {
            "single": SingleViewPolicy,
            "random": RandomNBVPolicy,
            "rule": frozen.rule_nbv,
            "oracle": lambda: OracleNBVPolicy(gts.__getitem__, frozen.DECISION_V1),
        }, frozen.decision_rule()
    if config == "v2":
        from activeperception import frozen_v2

        # oracle-v2 peeks at unvisited views: an offline upper bound, not run live
        return {
            "single": SingleViewPolicy,
            "random": RandomNBVPolicy,
            "rule": frozen_v2.rule_nbv,
        }, frozen_v2.decision_rule()
    raise ValueError(f"unknown config {config}")


class LiveWorld:
    """ObservationSource backed by the running ROS 2 graph."""

    name = "gazebo-live"

    def __init__(self, node: InspectorNode):
        self.node = node

    def observe(self, spec, viewpoint) -> Observation:
        return self.node.observe(spec, viewpoint)

    def ground_truth(self, spec):
        raise RuntimeError("the live world has no oracle pass; GT comes from the episode set")


class InspectorNode(Node):
    def __init__(self):
        super().__init__("inspector")
        p = {
            "episode_id": "",
            "episodes": "",
            "runs": "single:3",
            "out": "/work/runs/ros",
            "weights_dir": "/work/models",
            "device": "cpu",
            "settle_s": 2.5 / 30.0,
            "timeout_s": 60.0,
            "config": "v0",  # v0 (package defaults, pilot check), v1 or v2 (frozen)
        }
        for k, v in p.items():
            self.declare_parameter(k, v)
        self.prm = {k: self.get_parameter(k).value for k in p}
        self._cg = ReentrantCallbackGroup()
        self._cv = threading.Condition()
        self._latest: dict[str, Image] = {}
        for key in ("rgb", "depth"):
            self.create_subscription(
                Image, f"/inspector/{key}", self._image_cb(key), 10, callback_group=self._cg
            )
        self._pose_cli = self.create_client(
            SetEntityPose, "/world/inspection/set_pose/blocking", callback_group=self._cg
        )
        self._det_pub = self.create_publisher(Detection2DArray, "/inspection/detections", 10)
        self._dec_pub = self.create_publisher(String, "/inspection/decision", 10)
        self.detector = load_detector(FROZEN_DETECTOR, self.prm["weights_dir"], self.prm["device"])

    # ---- sensors -----------------------------------------------------------
    def _image_cb(self, key: str):
        def cb(msg: Image) -> None:
            with self._cv:
                self._latest[key] = msg
                self._cv.notify_all()

        return cb

    def latest_stamp_ns(self) -> int:
        with self._cv:
            return max((stamp_ns(m) for m in self._latest.values()), default=-1)

    def grab(self, after_ns: int) -> dict[str, Image]:
        deadline = time.monotonic() + self.prm["timeout_s"]
        with self._cv:
            while True:
                fresh = {k: m for k, m in self._latest.items() if stamp_ns(m) > after_ns}
                if len(fresh) == 2:
                    return fresh
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError(f"no fresh rgb+depth after {after_ns} ns")
                self._cv.wait(left)

    # ---- teleport ------------------------------------------------------------
    def teleport(self, pose, attempts: int = 5) -> None:
        req = SetEntityPose.Request()
        req.entity.name = CAMERA_MODEL
        req.entity.type = Entity.MODEL
        req.pose.position.x, req.pose.position.y, req.pose.position.z = pose.x, pose.y, pose.z
        w, x, y, z = pose_quaternion(pose.yaw, pose.pitch)
        o = req.pose.orientation
        o.w, o.x, o.y, o.z = w, x, y, z
        for _ in range(attempts):  # set_pose is idempotent, so a false reply can be retried
            done = threading.Event()
            fut = self._pose_cli.call_async(req)
            fut.add_done_callback(lambda _f, ev=done: ev.set())
            if not done.wait(self.prm["timeout_s"]):
                raise TimeoutError("set_pose service did not answer")
            if fut.result() is not None and fut.result().success:
                return
            time.sleep(0.2)
        raise RuntimeError("set_pose replied false")

    # ---- one observation -------------------------------------------------------
    def observe(self, spec, vp) -> Observation:
        self.teleport(vp.pose)
        t_ref = self.latest_stamp_ns()
        msgs = self.grab(t_ref + int(self.prm["settle_s"] * 1e9))
        rgb, depth = image_to_numpy(msgs["rgb"]), image_to_numpy(msgs["depth"])
        raw = self.detector.detect(rgb)
        w, h = spec.camera.width, spec.camera.height
        dets = tuple(make_detection(r[0], r[1:5], w, h) for r in raw)
        self._publish_detections(msgs["rgb"], dets)
        return Observation(
            viewpoint_id=vp.id,
            viewpoint=vp,
            detections=dets,
            zone_visible_fraction=zone_visible_fraction_from_depth(
                depth, spec.camera, vp.pose, spec.zone, "planar"
            ),
            timestamp=stamp_ns(msgs["rgb"]) / 1e9,
            image_ref=f"live:{spec.episode_id}#{vp.id}",
            obstacle_cells=obstacle_cells_from_depth(depth, spec.camera, vp.pose, spec.zone),
            location_visibility=location_visibility_from_depth(
                depth, spec.camera, vp.pose, spec.zone
            ),
            meta={"world": "gazebo-live", "detector": FROZEN_DETECTOR, "t_ref_ns": t_ref},
        )

    def _publish_detections(self, rgb_msg: Image, dets) -> None:
        arr = Detection2DArray()
        arr.header = rgb_msg.header
        for d in dets:
            det = Detection2D()
            det.header = rgb_msg.header
            x1, y1, x2, y2 = d.bbox
            det.bbox.center.position.x = (x1 + x2) / 2.0
            det.bbox.center.position.y = (y1 + y2) / 2.0
            det.bbox.size_x = x2 - x1
            det.bbox.size_y = y2 - y1
            hyp = ObjectHypothesisWithPose()
            hyp.hypothesis.class_id = TARGET_CLASS
            hyp.hypothesis.score = float(d.confidence)
            det.results.append(hyp)
            arr.detections.append(det)
        self._det_pub.publish(arr)

    # ---- episode loop -------------------------------------------------------------
    def run_all(self) -> dict:
        specs, gts, _ = load_episode_set(self.prm["episodes"])
        spec = next(s for s in specs if s.episode_id == self.prm["episode_id"])
        if not self._pose_cli.wait_for_service(timeout_sec=self.prm["timeout_s"]):
            raise TimeoutError("set_pose service not bridged")
        self.grab(-1)  # sensors are publishing
        policies, rule = policies_for(self.prm["config"], gts)
        world = LiveWorld(self)
        runs = []
        for item in self.prm["runs"].split(","):
            name, budget = item.split(":")
            t0 = time.monotonic()
            rec = run_episode(spec, world, policies[name](), rule, int(budget), run_seed=0)
            row = {
                "policy": name,
                "budget": int(budget),
                "viewpoint_sequence": list(rec.viewpoint_sequence),
                "decision": str(rec.decision),
                "confidence": rec.confidence,
                "max_conf_per_view": [o.max_confidence for o in rec.observations],
                "zone_visible_per_view": [o.zone_visible_fraction for o in rec.observations],
                "stamps_s": [o.timestamp for o in rec.observations],
                "seconds": round(time.monotonic() - t0, 2),
            }
            runs.append(row)
            self._dec_pub.publish(String(data=json.dumps({"episode_id": spec.episode_id, **row})))
            seq, dec = row["viewpoint_sequence"], row["decision"]
            self.get_logger().info(f"{spec.episode_id} {name}@{budget}: {dec} via {seq}")
        out = {
            "episode_id": spec.episode_id,
            "detector": f"{DETECTOR_VERSION}:{FROZEN_DETECTOR}",
            "device": self.detector.device,
            "decision_rule": rule.version,
            "config": self.prm["config"],
            "runs": runs,
        }
        path = Path(self.prm["out"]) / f"{spec.episode_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=1))
        return out


def main() -> None:
    rclpy.init()
    node = InspectorNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    try:
        node.run_all()
    finally:
        # stop spinning and wait for in-flight callbacks before destroying the node
        # (destroying first aborted once in 24 pilot episodes, after the record was written)
        executor.shutdown(timeout_sec=5.0)
        spinner.join(timeout=5.0)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
