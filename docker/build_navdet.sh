#!/usr/bin/env bash
# Build the Advanced B1 closed-loop image (Nav2 + CPU detector) on top of the Nav2 image.
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t "${IMAGE:-inspection-ap-navdet:jazzy-harmonic}" \
  --build-arg "NAV_IMAGE=${NAV_IMAGE:-inspection-ap-nav:jazzy-harmonic}" -f docker/Dockerfile.navdet docker/
