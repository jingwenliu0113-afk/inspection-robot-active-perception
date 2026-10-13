#!/usr/bin/env bash
# Advanced B1 / B2 closed-loop runs (decision 017): one fresh container per (episode, method,
# seed) from inspection-ap-navdet, WORKERS in parallel, resumable (a job with run.json is
# skipped; a failed job is retried once; attempts in $OUT/attempts.log).
#   ./docker/nav_b1.sh 3 nav-b1      (namespace -> data/episodes/{specs,gazebo}-<ns>.json,
#                                     renders/<ns>, runs/<ns>/teleport-detector-v1.jsonl)
set -uo pipefail
cd "$(dirname "$0")/.."
WORKERS="$1"; NS="$2"
IMAGE="${IMAGE:-inspection-ap-navdet:jazzy-harmonic}"
OUT="${OUT:-runs/$NS}"
SPECS="data/episodes/specs-$NS.json"; GT="data/episodes/gazebo-$NS.json"
RENDERS="renders/$NS"; TDETS="runs/$NS/teleport-detector-v1.jsonl"
JOBS="${JOBS:-single:0 rule:0 oracle:0 random:0 random:1 random:2}"
LOCK=/tmp/ai-portfolio-mac-heavy.lock
if [ -e "$LOCK" ] && ! python3 -c "import fcntl,sys; f=open('$LOCK'); fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)" 2>/dev/null; then
  echo "Mac heavy lock $LOCK is held by another project; not running." >&2
  exit 75
fi
mkdir -p "$OUT"
EPISODES="${EPISODES:-$(python3 -c "import json,sys; print(' '.join(e['episode_id'] for e in json.load(open(sys.argv[1]))['episodes']))" "$SPECS")}"

run_job() {
  local ep="$1" method="$2" seed="$3"
  docker run --rm -i --name "inspection-ap-nav-b1-$$-$ep-$method-$seed" \
    -e OUT="$OUT" -e EP="$ep" -e METHOD="$method" -e SEED="$seed" -e SPECS="$SPECS" -e GT="$GT" \
    -e RENDERS="$RENDERS" -e TDETS="$TDETS" \
    -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST -e ROS_DOMAIN_ID=37 \
    -v "$(pwd)":/work -w /work "$IMAGE" bash -c '
set -eo pipefail
source /opt/ros/jazzy/setup.bash
W="$OUT/$EP/_world"; R="$OUT/$EP/$METHOD-s$SEED"; rm -rf "$R"; mkdir -p "$R"
python3 -m activeperception.nav.b1_driver prepare --specs "$SPECS" --episode "$EP" --out "$OUT/_worlds"
W="$OUT/_worlds/$EP"
ros2 launch nav2_bringup tb4_simulation_launch.py headless:=True use_rviz:=False \
  world:="/work/$W/world.sdf" map:="/work/$W/map.yaml" params_file:="/work/$W/nav2_params.yaml" \
  robot_sdf:="/work/$W/robot.urdf" $(cat "$W/launch_args.txt") > "$R/launch.log" 2>&1 &
LAUNCH=$!
ros2 run ros_gz_bridge parameter_bridge "/gt/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry" \
  --ros-args -p use_sim_time:=true > "$R/gt_bridge.log" 2>&1 &
BRIDGE=$!
status=0
timeout 3600 python3 -m activeperception.nav.b1_driver run --specs "$SPECS" --episodes-gt "$GT" \
  --renders "$RENDERS" --teleport-detections "$TDETS" --episode "$EP" --method "$METHOD" \
  --seed "$SEED" --budget 5 --out "$OUT" > "$R/driver.log" 2>&1 || status=$?
kill -INT $BRIDGE $LAUNCH 2>/dev/null || true
sleep 5
exit $status
' > /dev/null 2>&1
}

worker() {
  local k="$1" i=0
  for ep in $EPISODES; do
    for job in $JOBS; do
      method="${job%%:*}"; seed="${job##*:}"
      if [ $((i % WORKERS)) -eq "$k" ] && [ ! -f "$OUT/$ep/$method-s$seed/run.json" ]; then
        for attempt in 1 2; do
          run_job "$ep" "$method" "$seed"; rc=$?
          echo "$(date -u +%FT%TZ) $ep $method-s$seed attempt $attempt exit $rc" >> "$OUT/attempts.log"
          [ -f "$OUT/$ep/$method-s$seed/run.json" ] && break
        done
      fi
      i=$((i + 1))
    done
  done
}

pids=()
for k in $(seq 0 $((WORKERS - 1))); do worker "$k" & pids+=($!); done
for pid in "${pids[@]}"; do wait "$pid"; done
find "$OUT" -name run.json | wc -l
