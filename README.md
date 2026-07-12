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
| `agent-core` | ✓ | — | ✓ | **Ollama direct agent.** A Python ROS 2 node that subscribes to `/spatial_coords` and `/voice_commands`, builds a prompt, queries Ollama's HTTP API, parses the JSON response, and publishes to `/target_goal`, `/grasp_command`, or `/object_spawn`. Minimal dependencies — single container, no extra framework. |
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
| `ROS_DOMAIN_ID` | `42` | all | ROS 2 DDS domain ID. Change if multiple ROS 2 stacks run on the same network. |

## RViz2 Visualization — X11 Forwarding Setup

The `visualize.launch.py` file runs RViz2 inside the Docker `ros2` container. To see the RViz2 window on your host desktop, you need X11 forwarding configured for your OS.

### macOS

**1. Install XQuartz**

```bash
brew install --cask xquartz
```

Log out and back in, or restart your machine.

**2. Allow XQuartz network connections**

Open XQuartz, go to **Settings → Security** and check **Allow connections from network clients**, or run:

```bash
defaults write org.xquartz.X11 enable_connections -bool true
```

Restart XQuartz.

**3. Authorize your IP**

```bash
xhost + $(ipconfig getifaddr en0)
```

(Replace `en0` with `en1` if you use Wi-Fi.)

**4. Launch with RViz2**

```bash
# Via convenience script:
./scripts/launch/rviz2-macos.sh

# Or directly:
# Start the stack in the background first
docker compose -f docker/docker-compose.yml --profile ollama-agent up -d

# Launch RViz2 into the running container
docker compose -f docker/docker-compose.yml --profile ollama-agent run \
  --rm \
  -e DISPLAY=$(ipconfig getifaddr en0):0 \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  ros2 \
  ros2 launch mock_hmi_core visualize.launch.py
```

RViz2 opens as a native window. Close it with Ctrl+C in the terminal when done.

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
  ros2 launch mock_hmi_core visualize.launch.py
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
  ros2 launch mock_hmi_core visualize.launch.py
```

**Alternative — WSL2 native with WSLg (Windows 11):**  
If you have Windows 11 with WSLg, X11 forwarding works automatically without VcXsrv. Just skip to step 4.

---

### Troubleshooting (All Platforms)

| Symptom | Fix |
|---------|-----|
| `cannot connect to X server` | X11 server isn't running or `xhost +` wasn't run |
| Window opens but is completely black | Check `docker logs spatial_hmi_ros2` for errors; ensure `robot_state_publisher` started |
| RViz2 shows grid but no arm model | The `robot_description` parameter wasn't loaded — the URDF might not be found |
| `Error: package 'mock_hmi_core' not found` | Run `colcon build` inside the ros2 container or rebuild the image |
| Permission denied on `/tmp/.X11-unix` | Ensure the directory exists on your host (`ls /tmp/.X11-unix`) |

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
| `ROS_DOMAIN_ID` | `42` | ROS 2 DDS domain |
