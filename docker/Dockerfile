# syntax=docker/dockerfile:1
# Formal simulation platform (decision 001 + appendix B): ROS 2 Jazzy + Gazebo Harmonic via the
# ROS vendor packages (official Jazzy/Harmonic pairing), Ubuntu 24.04, headless software
# rendering (Mesa llvmpipe / EGL surfaceless). No OSRF gz-harmonic: one Harmonic copy only.
#
# Base pinned by digest (pulled 2026-10-13, linux/arm64). apt packages cannot be pinned long
# term (packages.ros.org keeps only the latest build), so docker/record_versions.sh writes the
# exact package versions to docs/platform/versions.md, which is committed with every rebuild.
ARG BASE_IMAGE=ros@sha256:066420e07f60aa18262f2479981def87ebcfcec42eefb0c0c57c4a46098348ca
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ros-jazzy-ros-gz-sim ros-jazzy-ros-gz-bridge ros-jazzy-ros-gz-image ros-jazzy-ros-gz-interfaces \
      ros-jazzy-vision-msgs \
      python3-numpy python3-colcon-common-extensions \
      libegl1 libegl-mesa0 libgl1-mesa-dri libgbm1 mesa-utils xvfb \
 && rm -rf /var/lib/apt/lists/*

# Deterministic CPU rendering. ogre2 needs OpenGL >= 3.3; llvmpipe provides 4.5.
ENV LIBGL_ALWAYS_SOFTWARE=1 \
    GALLIUM_DRIVER=llvmpipe \
    MESA_GL_VERSION_OVERRIDE=4.5 \
    GZ_SIM_RESOURCE_PATH=/work/gazebo/models \
    PYTHONPATH=/work

WORKDIR /work
CMD ["bash"]
