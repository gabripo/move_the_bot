#!/bin/bash
set -e

source /opt/ros/humble/setup.bash
source /ros_ws/install/setup.bash

export LIBGL_ALWAYS_SOFTWARE=true
export GALLIUM_DRIVER=llvmpipe
export LP_NUM_THREADS=0

export DISPLAY=:99

RES_W=1440
RES_H=900

# Start Xvfb (virtual framebuffer) — 1440x900 fits MacBook screens well
Xvfb :99 -screen 0 ${RES_W}x${RES_H}x24 +extension GLX &
XVFB_PID=$!
sleep 2

# Openbox config to maximise new windows
mkdir -p /root/.config/openbox
cat > /root/.config/openbox/rc.xml << 'EOF'
<?xml version="1.0"?>
<openbox_config>
  <applications>
    <application class="*">
      <maximized>yes</maximized>
    </application>
  </applications>
</openbox_config>
EOF

# Start lightweight window manager
openbox --sm-disable --config-file /root/.config/openbox/rc.xml &
sleep 1

# Debug: print OpenGL info
echo "--- OpenGL Info ---"
glxinfo -B 2>&1 | grep -E "OpenGL|renderer|version" || echo "(glxinfo not available)"
echo "-------------------"

# Start x11vnc to share the virtual display
x11vnc -display :99 -forever -passwd rviz2 -quiet &
X11VNC_PID=$!

echo ""
echo "=================================================="
echo " RViz2 — VNC at localhost:5901  password: rviz2"
echo "--------------------------------------------------"
echo " Mouse controls (click inside RViz2 window first):"
echo "   Left-drag        = rotate 3D view"
echo "   Scroll / Right-drag = zoom in/out"
echo "   Middle-drag      = pan"
echo " Keyboard:"
echo "   Ctrl+D           = toggle Displays panel"
echo "   Ctrl+R           = reset camera view"
echo "=================================================="
echo ""

# Launch all nodes (including rviz2) in background
ros2 launch mock_hmi_core visualize.launch.py &
LAUNCH_PID=$!

# Wait for rviz node, then inject robot_description (with retries)
RD=$(cat /ros_ws/src/mock_hmi_core/urdf/simple_arm.urdf)
for i in 1 2 3 4 5; do
  if ros2 param set /rviz robot_description "$RD" 2>/dev/null; then
    echo "robot_description set on /rviz"
    break
  fi
  echo "Waiting for /rviz node... (attempt $i)"
  sleep 2
done

# Maximise the rviz2 window
sleep 1
wmctrl -r "RViz2*" -b add,maximized_vert,maximized_horz 2>/dev/null || true

# Wait for launch to exit
wait $LAUNCH_PID
