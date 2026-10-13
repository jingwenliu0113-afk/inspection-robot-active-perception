#!/usr/bin/env bash
# Render a spec set into a frame store with N parallel containers (decision 007).
#   ./docker/render.sh data/episodes/specs-detsel.json renders/detsel 3
# Each worker is its own container (own network namespace -> isolated gz-transport
# discovery); container names are inspection-ap-render-<pid>-<k> (MACHINE_POLICY).
# Before a large batch, refuse to run while another project holds the Mac heavy lock.
set -euo pipefail
cd "$(dirname "$0")/.."
SPECS="$1"; OUT="$2"; WORKERS="${3:-3}"; shift 3 || true
IMAGE="${IMAGE:-inspection-ap-sim:jazzy-harmonic}"
LOCK=/tmp/ai-portfolio-mac-heavy.lock
if [ -e "$LOCK" ] && ! python3 -c "import fcntl,sys; f=open('$LOCK'); fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)" 2>/dev/null; then
  echo "Mac heavy lock $LOCK is held by another project; not rendering." >&2
  exit 75
fi
IMAGE_ID="$(docker inspect --format '{{.Id}}' "$IMAGE")"
mkdir -p "$OUT"
pids=()
for k in $(seq 0 $((WORKERS - 1))); do
  docker run --rm -i --name "inspection-ap-render-$$-$k" -e AP_IMAGE_ID="$IMAGE_ID" \
    -v "$(pwd)":/work -w /work "$IMAGE" \
    python3 -m activeperception.sim.render --specs "$SPECS" --out "$OUT" \
      --worker "$k" --workers "$WORKERS" "$@" > "$OUT/_worker$k.log" 2>&1 &
  pids+=($!)
done
status=0
for pid in "${pids[@]}"; do wait "$pid" || status=1; done
tail -n 1 "$OUT"/_worker*.log
exit $status
