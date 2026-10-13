#!/usr/bin/env bash
# Record the formal simulation platform (decision 001) into docs/platform/versions.md.
# Run on the HOST after every image build and commit the output.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE="${IMAGE:-inspection-ap-sim:jazzy-harmonic}"
IMAGE_ID="$(docker inspect --format '{{.Id}}' "${IMAGE}")"
BASE="$(sed -n 's/^ARG BASE_IMAGE=//p' docker/Dockerfile)"
mkdir -p docs/platform
{
  echo "# Platform record"
  echo
  echo "generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "| item | value |"
  echo "|---|---|"
  echo "| image | \`${IMAGE}\` |"
  echo "| image id | \`${IMAGE_ID}\` |"
  echo "| base | \`${BASE}\` |"
  echo "| docker server | $(docker version --format '{{.Server.Version}} ({{.Server.Os}}/{{.Server.Arch}})') |"
  echo "| host | $(uname -sm) |"
  echo
  docker run --rm -i --name "inspection-ap-versions-$$" "${IMAGE}" bash -c '
    echo "\`\`\`"
    head -2 /etc/os-release
    echo "arch: $(uname -m)"
    echo "ROS_DISTRO: ${ROS_DISTRO:-unset}"
    gz sim --version 2>/dev/null | head -1 || true
    python3 --version
    eglinfo -B 2>/dev/null | grep -m1 "OpenGL core profile renderer" || true
    echo "\`\`\`"
    echo
    echo "## gz / ros / mesa packages"
    echo
    echo "\`\`\`"
    dpkg-query -W -f="\${Package} \${Version}\n" | grep -E "^(gz-|libgz-|python3-gz-|ros-jazzy-|libogre|mesa|libegl|libgl1|python3-numpy)" | sort
    echo "\`\`\`"'
} > docs/platform/versions.md
echo "wrote docs/platform/versions.md"
