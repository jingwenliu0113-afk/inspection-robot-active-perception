#!/usr/bin/env bash
# M2 smoke test, run INSIDE the container: ./docker/run.sh bash docker/smoke.sh
# Headless render of a pilot world; checks formats, teleport, freshness, determinism.
set -euo pipefail
cd /work
OUT=runs/smoke
mkdir -p "$OUT"
python3 -m activeperception.sim.sdf --namespace pilot --group 0 --variant 0 --out "$OUT/world.sdf"
gz sim -s -r --headless-rendering -v 2 "$OUT/world.sdf" > "$OUT/gz-server.log" 2>&1 &
GZ_PID=$!
trap 'kill $GZ_PID 2>/dev/null || true' EXIT
python3 -m activeperception.sim.gz_smoke --out "$OUT/smoke.json"
echo "smoke OK"
