"""TurtleBot 4 with an inspection mast camera (decision 015).

``build_urdf`` takes the xacro output of ``nav2_minimal_tb4_description``'s standard
TurtleBot 4 and

- removes the OAK-D ``rgbd_camera`` sensor (unused; saves software rendering time),
- adds a mast and ``inspector_camera_link`` 1.1 m above the ground, pitched down by
  ``scene.MAST_PITCH``, carrying the Core camera trio (RGB, depth, semantic segmentation)
  with the Core intrinsics and topics, so the frozen v2 sensing applies unchanged,
- adds a ground-truth odometry publisher on ``/gt/odom`` (world frame). GT is for scoring
  only: deployable code reads the AMCL estimate (``map -> base_link``) instead.

The segmentation camera is scoring-only as well (labels are never given to the decision).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ..sim.sdf import DEPTH_TOPIC, RGB_TOPIC, SEG_TOPIC, _camera_block
from ..types import CameraModel
from .scene import CONFIG, MAST_PITCH

CAMERA_LINK = "inspector_camera_link"
GT_ODOM_TOPIC = "/gt/odom"
# base_link rests BASE_REST_Z above the ground: -0.004 m, read once from /gt/odom in the B0
# dev run (nav-b0-g0000-v0, robot at rest). A fixed robot calibration, like any URDF
# offset; the mast joint puts the camera optical centre at CONFIG.ring_height at rest.
BASE_REST_Z = -0.004
CAMERA_ABOVE_BASE = CONFIG.ring_height - BASE_REST_Z
SENSOR_RATE_HZ = 5.0
_INERTIAL = (
    '<inertial><mass value="0.05"/>'
    '<inertia ixx="1e-4" ixy="0" ixz="0" iyy="1e-4" iyz="0" izz="1e-5"/></inertial>'
)


def _sensors(camera: CameraModel, rate: float) -> str:
    cam = _camera_block(camera)
    seg = cam.replace("<camera>", "<camera><segmentation_type>semantic</segmentation_type>")
    out = []
    for name, kind, topic, block in (
        ("inspector_rgb", "camera", RGB_TOPIC, cam),
        ("inspector_depth", "depth_camera", DEPTH_TOPIC, cam),
        ("inspector_segmentation", "segmentation_camera", SEG_TOPIC, seg),
    ):
        out.append(
            f'<sensor name="{name}" type="{kind}"><always_on>true</always_on>'
            f"<update_rate>{rate}</update_rate><visualize>false</visualize>"
            f"<topic>{topic}</topic>{block}</sensor>"
        )
    return "".join(out)


def mast_xml(camera: CameraModel, rate: float = SENSOR_RATE_HZ) -> str:
    return f"""<extra>
  <link name="inspector_mast_link">
    <visual><origin xyz="0 0 0.675"/><geometry><cylinder radius="0.015" length="0.75"/></geometry></visual>
    {_INERTIAL}
  </link>
  <joint name="inspector_mast_joint" type="fixed">
    <parent link="base_link"/><child link="inspector_mast_link"/><origin xyz="0 0 0"/>
  </joint>
  <link name="{CAMERA_LINK}">{_INERTIAL}</link>
  <joint name="inspector_camera_joint" type="fixed">
    <parent link="base_link"/><child link="{CAMERA_LINK}"/>
    <origin xyz="0 0 {CAMERA_ABOVE_BASE:.4f}" rpy="0 {MAST_PITCH:.6f} 0"/>
  </joint>
  <gazebo reference="{CAMERA_LINK}">{_sensors(camera, rate)}</gazebo>
  <gazebo>
    <plugin filename="gz-sim-odometry-publisher-system" name="gz::sim::systems::OdometryPublisher">
      <odom_frame>world</odom_frame><robot_base_frame>base_link</robot_base_frame>
      <odom_topic>{GT_ODOM_TOPIC}</odom_topic><tf_topic>/gt/tf</tf_topic>
      <odom_publish_frequency>30</odom_publish_frequency><dimensions>3</dimensions>
    </plugin>
  </gazebo>
</extra>"""


def build_urdf(tb4_urdf: str, camera: CameraModel | None = None) -> str:
    root = ET.fromstring(tb4_urdf)
    removed = 0
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "sensor" and child.get("name") == "rgbd_camera":
                parent.remove(child)
                removed += 1
    if removed != 1:
        raise ValueError(f"expected one OAK-D rgbd_camera sensor, found {removed}")
    for el in ET.fromstring(mast_xml(camera or CONFIG.camera)):
        root.append(el)
    return ET.tostring(root, encoding="unicode")
