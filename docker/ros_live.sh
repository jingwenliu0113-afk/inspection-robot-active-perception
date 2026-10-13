#!/usr/bin/env bash
# Live ROS 2 runs of the shared decision rule / policies (decision 001 appendix B,
# decision 007 pilot check 4). Host side:
#   ./docker/ros_live.sh data/episodes/gazebo-pilot.json "single:3,random:3,rule:3,oracle:3" ep1 ep2 ...
# One container (inspection-ap-ros) runs: colcon build -> for each episode: SDF from the
# episode set -> ros2 launch (gz sim + ros_gz_bridge + inspector) -> runs/ros/<episode>.json
set -euo pipefail
cd "$(dirname "$0")/.."
EPISODES="$1"; RUNS="$2"; shift 2
IMAGE="${IMAGE:-inspection-ap-ros:jazzy-harmonic}"
docker run --rm -i --name "inspection-ap-ros-$$" -v "$(pwd)":/work -w /work "$IMAGE" \
  bash -c '
set -eo pipefail
source /opt/ros/jazzy/setup.bash
cd /work/ros_ws && colcon build --symlink-install --packages-select inspection_ap_ros > /work/runs/ros_build.log 2>&1
source /work/ros_ws/install/setup.bash
cd /work
mkdir -p runs/ros/worlds
episodes="$1"; runs="$2"; shift 2
for ep in "$@"; do
  python3 -m activeperception.sim.sdf --specs "$episodes" --episode "$ep" --out "runs/ros/worlds/$ep.sdf" > /dev/null
  ros2 launch inspection_ap_ros inspect_episode.launch.py world:="/work/runs/ros/worlds/$ep.sdf" \
    episode_id:="$ep" episodes:="/work/$episodes" runs:="$runs" out:=/work/runs/ros 2>&1 \
    | grep -E "inspector.*(present|absent|inconclusive)|ERROR|Traceback|Error" || true
done
' _ "$EPISODES" "$RUNS" "$@"
