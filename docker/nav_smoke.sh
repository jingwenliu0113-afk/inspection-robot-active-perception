#!/usr/bin/env bash
# Advanced B0 compatibility smoke (decision 015 C1 / C2): stock TurtleBot 4 + Nav2 on Gazebo
# Harmonic, headless, in this project's own container (own network namespace; ROS 2
# discovery limited to localhost; never touches other projects' containers).
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="${IMAGE:-inspection-ap-nav:jazzy-harmonic}"
OUT="${OUT:-runs/nav-smoke}"
mkdir -p "$OUT"
docker run --rm -i --name "inspection-ap-nav-smoke-$$" -e OUT="$OUT" \
  -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST -e ROS_DOMAIN_ID=37 \
  -v "$(pwd)":/work -w /work "$IMAGE" bash -c '
set -eo pipefail
source /opt/ros/jazzy/setup.bash
ros2 launch nav2_bringup tb4_simulation_launch.py headless:=True use_rviz:=False x_pose:=-6.0 y_pose:=0.0 > "$OUT/launch.log" 2>&1 &
LAUNCH=$!
timeout 900 python3 -m activeperception.nav.smoke --out "$OUT/smoke.json" || echo "smoke exit=$?"
gz topic -e -t /stats -n 3 2>/dev/null | grep -E "real_time_factor" || true
kill -INT $LAUNCH; sleep 8; kill -9 $LAUNCH 2>/dev/null || true
'
