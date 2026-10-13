#!/usr/bin/env bash
# Build the ROS 2 live-integration image on top of the render image.
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t "${IMAGE:-inspection-ap-ros:jazzy-harmonic}" \
  --build-arg "SIM_IMAGE=${SIM_IMAGE:-inspection-ap-sim:jazzy-harmonic}" -f docker/Dockerfile.ros docker/
