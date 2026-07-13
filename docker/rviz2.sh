#!/bin/bash
set -e

source /opt/ros/humble/setup.bash
source /ros_ws/install/setup.bash

export LIBGL_ALWAYS_SOFTWARE=true
export GALLIUM_DRIVER=llvmpipe
export LP_NUM_THREADS=0

echo "RViz2 wrapper — Mesa software rendering: llvmpipe"
exec ros2 launch mock_hmi_core visualize.launch.py "$@"
