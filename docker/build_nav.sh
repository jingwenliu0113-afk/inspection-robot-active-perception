#!/usr/bin/env bash
# Build the Advanced B (Nav2) image on top of the render image (decision 015).
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t "${IMAGE:-inspection-ap-nav:jazzy-harmonic}" \
  --build-arg "SIM_IMAGE=${SIM_IMAGE:-inspection-ap-sim:jazzy-harmonic}" -f docker/Dockerfile.nav docker/
