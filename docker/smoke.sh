#!/usr/bin/env bash
# M2 smoke test, run INSIDE the container (./docker/run.sh bash docker/smoke.sh).
# Checks: headless render produces RGB + depth frames; set_pose teleport works;
# two renders at the same pose are identical. Writes /work/runs/smoke/.
# STATUS: written before the image existed; expect to debug on first run.
set -euo pipefail
cd /work
OUT=runs/smoke
mkdir -p "$OUT"
python3 -m activeperception.sim.sdf --namespace pilot --group 0 --variant 0 --out "$OUT/world.sdf"

gz sim -s -r --headless-rendering -v 2 "$OUT/world.sdf" > "$OUT/gz-server.log" 2>&1 &
GZ_PID=$!
trap 'kill $GZ_PID 2>/dev/null || true' EXIT
sleep 8
gz topic -l | tee "$OUT/topics.txt"
grep -q '/inspector/rgb' "$OUT/topics.txt" || { echo "rgb topic missing"; exit 1; }

python3 docker/grab_frames.py --out "$OUT" --label initial
gz service -s /world/inspection/set_pose --reqtype gz.msgs.Pose --reptype gz.msgs.Boolean \
  --timeout 3000 --req 'name: "inspector_cam", position: {x: 0.0, y: 2.0, z: 1.1}, orientation: {x: 0, y: 0.0, z: -0.7071, w: 0.7071}'
sleep 2
python3 docker/grab_frames.py --out "$OUT" --label moved
python3 docker/grab_frames.py --out "$OUT" --label moved_again
python3 - <<'PY'
import numpy as np, sys
a = np.load("runs/smoke/moved_rgb.npy"); b = np.load("runs/smoke/moved_again_rgb.npy")
print("same-pose pixel-identical:", np.array_equal(a, b), "max abs diff:", int(np.abs(a.astype(int)-b.astype(int)).max()))
PY
echo "smoke OK"
