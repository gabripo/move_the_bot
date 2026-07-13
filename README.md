# Spatial HMI Robotics

AI-powered spatial human-machine interface: control a simulated robotic arm using hand gestures, voice commands, or text prompts.

## Quick Start

### Prerequisites
- Docker Desktop 24+ with Docker Compose v2+
- 4 GB RAM minimum
- [Ollama](https://ollama.ai) installed locally with `llama3.2` model: `ollama pull llama3.2`

### Tutorials

| # | Topic | File |
|---|-------|------|
| 1 | Ollama Direct Agent (default, 4 containers) | [`tutorials/tutorial-1-ollama-agent.md`](tutorials/tutorial-1-ollama-agent.md) |
| 2 | OpenClaw Agent (6 containers, TS build required) | [`tutorials/tutorial-2-openclaw-agent.md`](tutorials/tutorial-2-openclaw-agent.md) |
| 3 | Both Agents (all 6 containers, side-by-side) | [`tutorials/tutorial-3-both-agents.md`](tutorials/tutorial-3-both-agents.md) |

Each tutorial includes build, launch, verify, example commands with "create an apple" / "grab the apple" scenarios, and cleanup steps.

Builtin spawnable objects: `apple`, `mug`, `bottle`, `cube`, `sphere`, `table`, `cylinder`, `can`. Unknown objects fall back to Sketchfab download (requires `SKETCHFAB_API_KEY`).

### Convenience Scripts

All launch configurations are available as executable scripts in `scripts/launch/`:

| Script | Purpose |
|--------|---------|
| `scripts/launch/ollama-agent.sh` | Tutorial 1 — Ollama direct agent |
| `scripts/launch/openclaw-agent.sh` | Tutorial 2 — OpenClaw agent (builds TS + launches) |
| `scripts/launch/all.sh` | Tutorial 3 — Both agents simultaneously |
| `scripts/launch/rviz2-macos.sh` | RViz2 visualization (macOS) |
| `scripts/launch/rviz2-linux.sh` | RViz2 visualization (Linux) |
| `scripts/launch/rviz2-windows.sh` | RViz2 visualization (Windows WSL2) |
| `scripts/launch/stop.sh` | Stop all running services |

Run any script from the project root: `./scripts/launch/ollama-agent.sh`

## Launch Options — Differences & Dependencies

The system supports three Docker Compose profiles, each starting a different set of services. All profiles share three always-on infrastructure services, then add profile-specific agent services on top.

### Service Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    PROFILE: ollama-agent                     │
│                                                             │
│  ollama ──→ ros2 ──→ web ←─→ stt  +  agent-core            │
│  (LLM)     (ROS 2)   (UI)   (ASR)   (direct Ollama)        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   PROFILE: openclaw-agent                    │
│                                                             │
│  ollama ──→ ros2 ──→ web ←─→ stt  +  openclaw              │
│  (LLM)     (ROS 2)   (UI)   (ASR)    (Gateway)              │
│                                       ─→ perception-bridge  │
│                                          (forwarder + SDK)   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      PROFILE: all                            │
│                                                             │
│  Both agent stacks run simultaneously — only one will       │
│  actuate the arm at a time (both publish to same topics).   │
└─────────────────────────────────────────────────────────────┘
```

### Service Dependency Graph

```
                     ┌──────────┐
                     │  ollama  │  (LLM — llama3.2)
                     └────┬─────┘
                          │  wait for healthy
                          ▼
                ┌─────────────────┐
                │      ros2       │  (ROS 2 + rosbridge + all actuation nodes)
                └────────┬────────┘
                     ┌───┴────┬─────┐
                     ▼        ▼     ▼
              ┌──────────┐ ┌────┐ ┌──────┐
              │   web    │ │ stt│ │agent │  (profile-specific)
              │ (nginx)  │ │(ASR)│ │-core │
              └──────────┘ └────┘ └──────┘
```

### Profile Comparison

| Service | `ollama-agent` | `openclaw-agent` | `all` | Description |
|---------|:---:|:---:|:---:|-------------|
| `ollama` | ✓ | ✓ | ✓ | LLM server with llama3.2. Pulls model on first start. |
| `ros2` | ✓ | ✓ | ✓ | ROS 2 Humble container. Runs all actuation nodes: `mock_kinematics_node` (IK solver), `virtual_scene_node` (table/world markers), `object_spawn_node` (3D model spawner), `rosbridge_websocket` (WebSocket API on :9090), `robot_state_publisher` (URDF). |
| `web` | ✓ | ✓ | ✓ | nginx:alpine serving the frontend at :80. Reverse-proxies `/ws/` → ros2:9090 for WebSocket, `/stt/` → stt:8000 for speech-to-text. |
| `stt` | ✓ | ✓ | ✓ | **Speech-to-text service.** Runs OpenAI Whisper tiny model in a FastAPI server. Accepts audio uploads at POST `/transcribe`, returns transcribed text. Used as fallback for Firefox (which lacks native `SpeechRecognition`). |
| `agent-core` | ✓ | — | ✓ | **Ollama direct agent.** A Python ROS 2 node that subscribes to `/spatial_coords` and `/voice_commands`, builds a prompt, queries Ollama's HTTP API, parses the JSON response, and publishes to `/target_goal`, `/grasp_command`, or `/object_spawn`. Uses a rule-based keyword parser as a fast-path, with Ollama fallback. See [Ollama Agent Internals](PLAN_ARCHITECTURE.md#ollama-agent-internals-agentic_core_nodepy) in `PLAN_ARCHITECTURE.md`. Minimal dependencies — single container, no extra framework. |
| `openclaw` | — | ✓ | ✓ | **OpenClaw Gateway.** A Node.js service running the OpenClaw agent framework with a custom tool plugin (`arm_move`, `arm_grasp`, `arm_release`, `spawn_object`). Connects to Ollama for LLM inference. Listens on WebSocket port 1455 for the perception forwarder. |
| `perception-bridge` | — | ✓ | ✓ | **Perception forwarder + SDK bridge.** Two components: a Python ROS 2 node (`perception_forwarder.py`) that forwards `/spatial_coords` and `/voice_commands` via stdin to a Node.js bridge process (`forwarder_bridge.ts`), which sends them to the OpenClaw Gateway using `openclaw-sdk`. Supports an alternative direct WebSocket backend (`perception_forwarder_ws.py`) via `OPENCLAW_FORWARDER_BACKEND=websocket`. |

### Service Dependencies

| Service | Depends On | Condition |
|---------|-----------|-----------|
| `ros2` | `ollama` | service started |
| `web` | `ros2`, `stt` | service started |
| `stt` | _(none)_ | always |
| `agent-core` | `ros2` | service started |
| `openclaw` | `ros2` | service started |
| `perception-bridge` | `openclaw`, `ros2` | service started |

### Choosing a Profile

| Use Case | Profile | Why |
|----------|---------|-----|
| Local development, testing | `ollama-agent` | Simpler stack (only 5 containers), fewer dependencies, faster startup. The direct agent queries Ollama directly without an intermediate framework. |
| Production, full agent framework | `openclaw-agent` | OpenClaw provides memory, multi-channel support, tool sandboxing, and is compatible with NemoClaw for hardware deployment. |
| Side-by-side comparison | `all` | Both agents run simultaneously. Useful for development and debugging, but only one should actuate at a time. |

### Launch File Options (Inside the ROS 2 Container)

The `deploy.launch.py` and `visualize.launch.py` ROS 2 launch files control which nodes start inside the `ros2` container:

| Launch File | Nodes | When to Use |
|-------------|-------|-------------|
| `deploy.launch.py` | mock_kinematics, virtual_scene, object_spawn, rosbridge_websocket, robot_state_publisher | Default. Headless deployment (no GUI). Used by `docker-compose.yml`. |
| `visualize.launch.py` | Same as above + **rviz2** | Development. Opens RViz2 for 3D visualization of the arm and scene. Requires X11 forwarding. |

### Environment Variables

| Variable | Default | Profiles | Description |
|----------|---------|----------|-------------|
| `SKETCHFAB_API_KEY` | _(unset)_ | all | API key for Sketchfab Download API. Enables fallback 3D model downloads for unknown objects. |
| `OPENCLAW_FORWARDER_BACKEND` | `sdk` | openclaw-agent | `sdk` uses the Node.js openclaw-sdk bridge; `websocket` uses direct Python WebSocket to the Gateway. |
| `OLLAMA_URL` | `http://ollama:11434/api/generate` | ollama-agent | Ollama API endpoint. Change to `http://host.docker.internal:11434/api/generate` to use a host-side Ollama. |
| `OLLAMA_MODEL` | `llama3.2` | ollama-agent | Ollama model tag. Light→capable: `llama3.2:3b-instruct-q4_K_M`, `llama3.2:3b`, `llama3.1:8b-instruct-q4_K_M`, `llama3.1:8b`. Auto-pulled on startup. |
| `ROS_DOMAIN_ID` | `42` | all | ROS 2 DDS domain ID. Change if multiple ROS 2 stacks run on the same network. |

## RViz2 Visualization

The `visualize.launch.py` file runs RViz2 inside the Docker `ros2` container.

### macOS

Docker Desktop for Mac has no GPU passthrough, so RViz2 uses a virtual framebuffer (Xvfb) with Mesa software rendering, shared via VNC.

**1. Launch with RViz2**

Just run the convenience script — it rebuilds, starts everything, and prints VNC connection info:

```bash
./scripts/launch/rviz2-macos.sh
```

**2. Connect to VNC**

When the script says `Connect to localhost:5901`:
- Press **Cmd+K** in Finder, enter `vnc://localhost:5901`, use password `rviz2`
- Or use any VNC client (TigerVNC: `brew install tigervnc && vncviewer localhost:5901`)

The RViz2 window appears inside the VNC session.

**3. Stop**

Press **Ctrl+C** in the terminal running the script. The container and VNC server stop automatically.

---

### Linux (Native)

On Linux, X11 forwarding is straightforward because Docker shares the same X server.

**1. Authorize X11 (if needed)**

```bash
xhost +local:
```

**2. Launch with RViz2**

```bash
# Via convenience script:
./scripts/launch/rviz2-linux.sh

# Or directly:
# Start the stack
docker compose -f docker/docker-compose.yml --profile ollama-agent up -d

# Launch RViz2
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

### Windows (WSL2 + VcXsrv)

**1. Install VcXsrv**

Download and install [VcXsrv Windows X Server](https://vcxsrv.sourceforge.io/). Launch **XLaunch**, select:
- **Multiple windows**
- **Display number: 0**
- **Start no client**
- Check **Disable access control**

Let it run in the background.

**2. Get your Windows host IP**

```powershell
ipconfig
```

Find the IPv4 address for your active adapter (e.g. `192.168.1.100`).

**3. Set DISPLAY in WSL2**

```bash
export DISPLAY=192.168.1.100:0
```

Add this line to `~/.bashrc` (or `~/.zshrc`) to make it permanent.

**4. Launch with RViz2**

```bash
# Via convenience script:
./scripts/launch/rviz2-windows.sh

# Or directly:
# Start the stack
docker compose -f docker/docker-compose.yml --profile ollama-agent up -d

# Launch RViz2
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

### Troubleshooting (All Platforms)

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

To see the pre-configured RViz2 layout, check `launch/visualize.rviz`. It shows Grid, TF frames, the RobotModel, and the `/scene_markers` / `/spawned_objects` topics.

## Architecture

See `PLAN_ARCHITECTURE.md` for full architecture documentation.

## Documentation

| File | Content |
|------|---------|
| `PLAN_ARCHITECTURE.md` | System architecture and data flow |
| `PLAN_DESIGN_CHOICES.md` | Design decisions and rationale |
| `PLAN_PROMPTS.md` | All LLM prompts and skill definitions |
| `PLAN_TEST_STRATEGY.md` | Test plan and coverage |

## Development

```bash
# Generate placeholder 3D models
python3 scripts/generate_placeholder_glbs.py

# Run unit tests (no Docker needed)
pip install pytest && pytest tests/unit/

# Run integration tests (requires running stack)
docker compose -f docker/docker-compose.yml --profile ollama-agent up -d
pytest tests/integration/
docker compose down

# Run tests with mock Ollama (CI)
docker compose -f docker-compose.test.yml up --abort-on-container-exit --build
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SKETCHFAB_API_KEY` | _(unset)_ | API key for 3D model fallback downloads |
| `OPENCLAW_FORWARDER_BACKEND` | `sdk` | `sdk` (Node.js bridge) or `websocket` (direct) |
| `OLLAMA_URL` | `http://ollama:11434/api/generate` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llama3.2` | Ollama model tag (e.g. `llama3.2:3b-instruct-q4_K_M`, `llama3.1:8b`) |
| `ROS_DOMAIN_ID` | `42` | ROS 2 DDS domain |
