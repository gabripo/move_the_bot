# shellcheck shell=sh
# Architecture detection for ROS 2 Docker image.
# Source this from launch scripts:  . "$SCRIPT_DIR/_arch_detect.sh"
# Sets ROS2_BASE_IMAGE and ROS2_PLATFORM for native ARM64 builds.

ARCH="$(uname -m)"
case "$ARCH" in
  arm64|aarch64)
    export ROS2_DOCKERFILE="${ROS2_DOCKERFILE:-docker/Dockerfile.ros2.arm64}"
    export ROS2_PLATFORM="${ROS2_PLATFORM:-linux/arm64}"
    echo " Detected ARM64 — using native Dockerfile: $ROS2_DOCKERFILE"
    ;;
  *)
    # amd64 — use the standard Dockerfile
    export ROS2_DOCKERFILE="${ROS2_DOCKERFILE:-docker/Dockerfile.ros2}"
    unset ROS2_PLATFORM
    ;;
esac
