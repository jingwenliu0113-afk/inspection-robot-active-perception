# syntax=docker/dockerfile:1
# Formal simulation platform (decision 001): ROS 2 Jazzy (ros-base) + Gazebo Harmonic,
# Ubuntu 24.04, headless software rendering (Mesa llvmpipe / EGL surfaceless).
#
# Pinning: after the first successful pull, record the base digest and rebuild with it:
#   docker pull ros:jazzy-ros-base
#   docker inspect --format '{{index .RepoDigests 0}}' ros:jazzy-ros-base
#   docker build --build-arg BASE_IMAGE=ros@sha256:<digest> ...
# Then run docker/record_versions.sh and commit docs/platform/.
ARG BASE_IMAGE=ros:jazzy-ros-base
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

# Gazebo Harmonic from packages.osrfoundation.org (arm64 and amd64 builds exist for noble).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg ca-certificates lsb-release \
 && curl -fsSL https://packages.osrfoundation.org/gazebo.gpg \
      -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
      > /etc/apt/sources.list.d/gazebo-stable.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      gz-harmonic \
      python3-gz-transport13 python3-gz-msgs10 python3-gz-sim8 \
      python3-numpy \
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
