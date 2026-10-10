#!/usr/bin/env bash
# Build the simulation image. Default platform follows the host (arm64 on Apple Silicon).
# Fallback (decision 001, option B): PLATFORM=linux/amd64 ./docker/build.sh on gpu-server.
set -euo pipefail
cd "$(dirname "$0")/.."
PLATFORM="${PLATFORM:-linux/$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')}"
BASE_IMAGE="${BASE_IMAGE:-ros:jazzy-ros-base}"
IMAGE="${IMAGE:-inspection-ap-sim:jazzy-harmonic}"
echo "building ${IMAGE} for ${PLATFORM} from ${BASE_IMAGE}"
docker build --platform "${PLATFORM}" --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
  -t "${IMAGE}" -f docker/Dockerfile docker/
