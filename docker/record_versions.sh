#!/usr/bin/env bash
# Record the platform versions inside the container into docs/platform/ (commit the output).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p docs/platform
{
  echo "# Platform record"
  echo
  echo "generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo '```'
  cat /etc/os-release | head -2
  echo "arch: $(uname -m)"
  echo "ROS_DISTRO: ${ROS_DISTRO:-unset}"
  gz sim --version 2>/dev/null | head -1 || true
  echo '```'
  echo
  echo "## gz / ros packages"
  echo
  echo '```'
  dpkg-query -W -f='${Package} ${Version}\n' | grep -E '^(gz-|libgz-|python3-gz-|ros-jazzy-|libogre|mesa|libegl|libgl1)' | sort
  echo '```'
} > docs/platform/versions.md
echo "wrote docs/platform/versions.md"
