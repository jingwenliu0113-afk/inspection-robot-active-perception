#!/usr/bin/env bash
# Run a command inside the simulation image with the repo mounted at /work.
# Only this project's own container name is used (MACHINE_POLICY: never touch other projects').
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="${IMAGE:-inspection-ap-sim:jazzy-harmonic}"
NAME="inspection-ap-sim-$$"
exec docker run --rm -i --name "${NAME}" -v "$(pwd)":/work -w /work "${IMAGE}" "$@"
