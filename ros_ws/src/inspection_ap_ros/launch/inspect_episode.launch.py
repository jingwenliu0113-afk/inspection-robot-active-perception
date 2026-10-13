"""One episode live: gz sim (headless) + ros_gz_bridge + inspector node.

    ros2 launch inspection_ap_ros inspect_episode.launch.py \
        world:=/work/runs/ros/worlds/pilot-g0000-v0.sdf episode_id:=pilot-g0000-v0 \
        episodes:=/work/data/episodes/gazebo-pilot.json runs:=single:3,rule:3 out:=/work/runs/ros

The launch shuts down when the inspector exits.
"""

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    ExecuteProcess,
    RegisterEventHandler,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

BRIDGED = [
    "/inspector/rgb@sensor_msgs/msg/Image[gz.msgs.Image",
    "/inspector/depth@sensor_msgs/msg/Image[gz.msgs.Image",
    "/world/inspection/set_pose/blocking@ros_gz_interfaces/srv/SetEntityPose",
]


def generate_launch_description():
    args = {
        "world": "",
        "episode_id": "",
        "episodes": "/work/data/episodes/gazebo-pilot.json",
        "runs": "single:3,random:3,rule:3,oracle:3",
        "out": "/work/runs/ros",
        "weights_dir": "/work/models",
        "device": "cpu",
    }
    decl = [DeclareLaunchArgument(k, default_value=v) for k, v in args.items()]
    gz_cmd = ["gz", "sim", "-s", "-r", "--headless-rendering", "-v", "1"]
    gz = ExecuteProcess(cmd=[*gz_cmd, LaunchConfiguration("world")], output="log")
    bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        arguments=BRIDGED,
        output="log",
    )
    inspector = Node(
        package="inspection_ap_ros",
        executable="inspector",
        output="screen",
        parameters=[{k: LaunchConfiguration(k) for k in args if k != "world"}],
    )
    stop = RegisterEventHandler(
        OnProcessExit(target_action=inspector, on_exit=[EmitEvent(event=Shutdown())])
    )
    return LaunchDescription([*decl, gz, bridge, inspector, stop])
