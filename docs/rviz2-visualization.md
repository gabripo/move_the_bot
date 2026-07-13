# RViz2 Visualization

The `visualize.launch.py` file runs RViz2 inside the Docker `ros2` container.

## macOS

Docker Desktop for Mac has no GPU passthrough, so RViz2 uses a virtual framebuffer (Xvfb) with Mesa software rendering, shared via VNC.

### 1. Launch with RViz2

Just run the convenience script — it rebuilds, starts everything, and prints VNC connection info:

```bash
./scripts/launch/rviz2-macos.sh
```

### 2. Connect to VNC

When the script says `Connect to localhost:5901`:
- Press **Cmd+K** in Finder, enter `vnc://localhost:5901`, use password `rviz2`
- Or use any VNC client (TigerVNC: `brew install tigervnc && vncviewer localhost:5901`)

The RViz2 window appears inside the VNC session.

### 3. Stop

Press **Ctrl+C** in the terminal running the script. The container and VNC server stop automatically.

---

## Linux (Native)

On Linux, X11 forwarding is straightforward because Docker shares the same X server.

### 1. Authorize X11 (if needed)

```bash
xhost +local:
```

### 2. Launch with RViz2

```bash
# Via convenience script:
./scripts/launch/rviz2-linux.sh

# Or directly:
docker compose -f docker/docker-compose.yml --profile ollama-agent up -d
docker compose -f docker/docker-compose.yml --profile ollama-agent run \
  --rm \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.Xauthority:/root/.Xauthority:ro \
  ros2 \
  /rviz2.sh
```

No extra software needed — works out of the box on any Linux desktop.

---

## Windows (WSL2 + VcXsrv)

### 1. Install VcXsrv

Download and install [VcXsrv Windows X Server](https://vcxsrv.sourceforge.io/). Launch **XLaunch**, select:
- **Multiple windows**
- **Display number: 0**
- **Start no client**
- Check **Disable access control**

Let it run in the background.

### 2. Get your Windows host IP

```powershell
ipconfig
```

Find the IPv4 address for your active adapter (e.g. `192.168.1.100`).

### 3. Set DISPLAY in WSL2

```bash
export DISPLAY=192.168.1.100:0
```

Add this line to `~/.bashrc` (or `~/.zshrc`) to make it permanent.

### 4. Launch with RViz2

```bash
# Via convenience script:
./scripts/launch/rviz2-windows.sh

# Or directly:
docker compose -f docker/docker-compose.yml --profile ollama-agent up -d
docker compose -f docker/docker-compose.yml --profile ollama-agent run \
  --rm \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  ros2 \
  /rviz2.sh
```

**Alternative — WSL2 native with WSLg (Windows 11):**  
If you have Windows 11 with WSLg, X11 forwarding works automatically without VcXsrv. Just skip to step 4.

---

## Troubleshooting (All Platforms)

| Symptom | Fix |
|---------|-----|
| `cannot connect to X server` | X11 server isn't running or `xhost +` wasn't run |
| `could not connect to display` | (macOS VNC) Connection refused — press Ctrl+C to stop, wait 5s, and re-run the script |
| Window opens but is completely black | Check `docker logs spatial_hmi_ros2` for errors; ensure `robot_state_publisher` started |
| RViz2 shows grid but no arm model | The `robot_description` parameter wasn't loaded — the URDF might not be found |
| `Error: package 'mock_hmi_core' not found` | Run `colcon build` inside the ros2 container or rebuild the image |
| VNC shows grey screen / no window | Wait a few seconds for RViz2 to initialize; the virtual display starts before RViz2 |
| `libGL error: No matching fbConfigs or visuals found` / `Failed to create an OpenGL context` (macOS) | Two possible causes: (1) GLX is disabled in XQuartz — run `defaults write org.xquartz.X11 enable_iglx -bool true`, quit and restart XQuartz. (2) Docker Desktop has no GPU passthrough — the image includes Mesa software rendering. Use `LIBGL_ALWAYS_SOFTWARE=1`, `GALLIUM_DRIVER=llvmpipe`, `MESA_GL_VERSION_OVERRIDE=3.3`, `MESA_GLSL_VERSION_OVERRIDE=330`. The convenience script handles both. |
| `OpenGL 1.5 is not supported` (macOS) | The softpipe Gallium driver only supports OpenGL ~1.5. Set `GALLIUM_DRIVER=llvmpipe` to use the LLVM-based software rasterizer, which supports OpenGL 3.3+. Also set `MESA_GL_VERSION_OVERRIDE=3.3` and `MESA_GLSL_VERSION_OVERRIDE=330`. |

## RViz2 Layout

The pre-configured layout is at `launch/visualize.rviz`. It shows:
- **Grid** — ground plane
- **TF** — coordinate frames for each link
- **MarkerArray (SceneMarkers)** — table, walls, and static scene objects published on `/visualization_marker_array`
- **MarkerArray (SpawnedObjects)** — dynamically spawned objects (apple, mug, bottle, etc.) on `/visualization_marker_array`
