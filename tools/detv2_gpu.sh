#!/usr/bin/env bash
# detector-v2 training on the RTX 5070 Ti (decision 027), from the Mac.
#   tools/detv2_gpu.sh check      # GPU idle? lock free? (no changes)
#   tools/detv2_gpu.sh sync       # code + manifests + train/dev images -> gpu-server (~0.6 MB/s)
#   tools/detv2_gpu.sh train      # the three pre-registered configs, one flock -n each
#   tools/detv2_gpu.sh fetch      # weights + logs back to runs/detv2/<config>/
#
# MACHINE_POLICY: the heavy step runs under `flock -n /tmp/ai-portfolio-gpu.lock`; if the lock
# is held or nvidia-smi shows another project, stop (exit 75) - never wait for, steal or delete
# the lock. Uses the existing project venv `.venv-det` on gpu-server; the WSL system is not
# touched. The test manifest is never copied (decision 027: test runs only in the formal step).
set -euo pipefail
cd "$(dirname "$0")/.."
REMOTE_DIR='~/ai-portfolio/inspection-robot-active-perception'
WSL='wsl.exe -d Ubuntu-22.04 -- bash -lc'
CONFIGS="base lowlr negheavy"

remote() { ssh gpu-server "$WSL \"cd $REMOTE_DIR && $1\""; }

case "${1:-}" in
  check)
    ssh gpu-server "$WSL 'nvidia-smi --query-gpu=name,utilization.gpu,memory.used --format=csv'"
    ssh gpu-server "$WSL 'flock -n /tmp/ai-portfolio-gpu.lock true && echo lock-free || echo LOCK-HELD'"
    ;;
  sync)
    # code and the train / dev manifests of the committed HEAD (no git credentials needed remotely)
    git archive --format=tar HEAD activeperception pyproject.toml uv.lock data/detv2 \
      ':(exclude)data/detv2/test.csv' | ssh gpu-server "$WSL \"cd $REMOTE_DIR && tar -xf -\""
    # images: train + dev only, as a tar stream (no rsync dependency on the remote)
    list="$(mktemp)"
    for split in train dev; do
      python3 - "$split" <<'EOF' > "$list"
import csv, sys
for r in csv.DictReader(open(f"data/detv2/{sys.argv[1]}.csv")):
    print(f"data/raw/detv2/{r['source']}/{r['image_id']}.jpg")
EOF
      tar -cf - -T "$list" | ssh gpu-server "$WSL \"cd $REMOTE_DIR && tar -xf -\""
    done
    rm -f "$list"
    remote "test -f models/fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth && echo weights-ok"
    ;;
  train)
    for c in $CONFIGS; do
      remote "flock -n /tmp/ai-portfolio-gpu.lock .venv-det/bin/python -m activeperception.detv2.train \
        --train data/detv2/train.csv --config $c --device cuda --out runs/detv2/$c" || {
        echo "GPU lock held or training failed for $c: stop, record as blocked (MACHINE_POLICY)" >&2
        exit 75
      }
    done
    ;;
  fetch)
    for c in $CONFIGS; do
      mkdir -p "runs/detv2/$c"
      ssh gpu-server "$WSL \"cd $REMOTE_DIR && tar -cf - runs/detv2/$c\"" | tar -xf -
    done
    ;;
  *)
    sed -n '2,12p' "$0"; exit 2 ;;
esac
