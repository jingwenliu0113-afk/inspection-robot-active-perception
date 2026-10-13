#!/usr/bin/env bash
# Live ROS 2 runs of the shared decision rule / policies (decision 001 appendix B,
# decision 007 pilot check 4). Host side:
#   ./docker/ros_live.sh data/episodes/gazebo-pilot.json "single:3,random:3,rule:3,oracle:3" ep1 ep2 ...
#   CONFIG=v2 OUT=runs/ros-v2 ./docker/ros_live.sh ...   (frozen v1 / v2; default v0)
# One container (inspection-ap-ros) runs: colcon build -> for each episode: SDF from the
# episode set -> ros2 launch (gz sim + ros_gz_bridge + inspector) -> runs/ros/<episode>.json
set -euo pipefail
cd "$(dirname "$0")/.."
EPISODES="$1"; RUNS="$2"; shift 2
IMAGE="${IMAGE:-inspection-ap-ros:jazzy-harmonic}"
CONFIG="${CONFIG:-v0}"
OUT="${OUT:-runs/ros}"
docker run --rm -i --name "inspection-ap-ros-$$" -e CONFIG="$CONFIG" -e OUT="$OUT" \
  -v "$(pwd)":/work -w /work "$IMAGE" \
  bash -c '
set -eo pipefail
source /opt/ros/jazzy/setup.bash
cd /work/ros_ws && colcon build --symlink-install --packages-select inspection_ap_ros > /work/runs/ros_build.log 2>&1
source /work/ros_ws/install/setup.bash
cd /work
mkdir -p "$OUT/worlds"
episodes="$1"; runs="$2"; shift 2
for ep in "$@"; do
  python3 -m activeperception.sim.sdf --specs "$episodes" --episode "$ep" --out "$OUT/worlds/$ep.sdf" > /dev/null
  ros2 launch inspection_ap_ros inspect_episode.launch.py world:="/work/$OUT/worlds/$ep.sdf" \
    episode_id:="$ep" episodes:="/work/$episodes" runs:="$runs" out:="/work/$OUT" config:="$CONFIG" 2>&1 \
    | grep -E "inspector.*(present|absent|inconclusive)|ERROR|Traceback|Error" || true
done
' _ "$EPISODES" "$RUNS" "$@"
