#!/usr/bin/env bash
# Demo: one closed-loop Nav2 episode (Rule-NBV v2 on nav-b1 development data) + animation.
#   ./docker/demo.sh                    # nav-b1-g0001-v2: hydrant hidden behind a pillar at the start
#   ./docker/demo.sh nav-b1-g0001-v3    # same scene, no hydrant
# Needs the inspection-ap-navdet image (./docker/build_nav.sh && ./docker/build_navdet.sh) and the
# detector weights in models/ (docs/reproduce.md). About 1-1.5 minutes on an M-series Mac (2026-10-17: 64 s).
# Output: runs/demo/<episode>/rule-s0 (logs, frames), runs/demo/<episode>.gif / .png.
# Development data only; nothing under results/ is written.
set -euo pipefail
cd "$(dirname "$0")/.."
EP="${1:-nav-b1-g0001-v2}"
rm -rf "runs/demo/$EP/rule-s0"
OUT=runs/demo EPISODES="$EP" JOBS="rule:0" ./docker/nav_b1.sh 1 nav-b1
uv run python tools/make_demo.py --ns nav-b1 --run "runs/demo/$EP/rule-s0" \
  --gif "runs/demo/$EP.gif" --png "runs/demo/$EP.png"
