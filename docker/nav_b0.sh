#!/usr/bin/env bash
# Advanced B0 runs (decision 015): one fresh container per episode (own network namespace ->
# isolated ROS 2 / gz-transport discovery), WORKERS episodes in parallel, resumable
# (an episode with episode.json is skipped; a failed episode is retried once and the
# attempt is logged in $OUT/attempts.log).
#   ./docker/nav_b0.sh 2 nav-b0-g0000-v0 nav-b0-g0000-v1 ...
set -uo pipefail
cd "$(dirname "$0")/.."
WORKERS="$1"; shift
IMAGE="${IMAGE:-inspection-ap-nav:jazzy-harmonic}"
OUT="${OUT:-runs/nav-b0}"
LOCK=/tmp/ai-portfolio-mac-heavy.lock
if [ -e "$LOCK" ] && ! python3 -c "import fcntl,sys; f=open('$LOCK'); fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)" 2>/dev/null; then
  echo "Mac heavy lock $LOCK is held by another project; not running." >&2
  exit 75
fi
mkdir -p "$OUT"

run_episode() {
  local ep="$1"
  docker run --rm -i --name "inspection-ap-nav-b0-$$-$ep" -e OUT="$OUT" -e EP="$ep" \
    -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST -e ROS_DOMAIN_ID=37 \
    -v "$(pwd)":/work -w /work "$IMAGE" bash -c '
set -eo pipefail
source /opt/ros/jazzy/setup.bash
D="$OUT/$EP"; rm -rf "$D"; mkdir -p "$D"
python3 -m activeperception.nav.b0_driver prepare --episode "$EP" --out "$OUT"
ros2 launch nav2_bringup tb4_simulation_launch.py headless:=True use_rviz:=False \
  world:="/work/$D/world.sdf" map:="/work/$D/map.yaml" params_file:="/work/$D/nav2_params.yaml" \
  robot_sdf:="/work/$D/robot.urdf" $(cat "$D/launch_args.txt") > "$D/launch.log" 2>&1 &
LAUNCH=$!
ros2 run ros_gz_bridge parameter_bridge "/gt/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry" \
  --ros-args -p use_sim_time:=true > "$D/gt_bridge.log" 2>&1 &
BRIDGE=$!
status=0
timeout 5400 python3 -m activeperception.nav.b0_driver run --episode "$EP" --out "$OUT" > "$D/driver.log" 2>&1 || status=$?
kill -INT $BRIDGE $LAUNCH 2>/dev/null || true
sleep 5
exit $status
' > /dev/null 2>&1
}

worker() {
  local k="$1"; shift
  local i=0
  for ep in "$@"; do
    if [ $((i % WORKERS)) -eq "$k" ] && [ ! -f "$OUT/$ep/episode.json" ]; then
      for attempt in 1 2; do
        run_episode "$ep"; rc=$?
        echo "$(date -u +%FT%TZ) $ep attempt $attempt exit $rc" >> "$OUT/attempts.log"
        [ -f "$OUT/$ep/episode.json" ] && break
      done
    fi
    i=$((i + 1))
  done
}

pids=()
for k in $(seq 0 $((WORKERS - 1))); do worker "$k" "$@" & pids+=($!); done
for pid in "${pids[@]}"; do wait "$pid"; done
ls "$OUT"/*/episode.json 2>/dev/null | wc -l
