# Tutorial 1: Ollama Direct Agent (Default)

**What this launches:** 5 containers — `ollama` (LLM), `ros2` (ROS 2 + actuation + rosbridge), `web` (nginx frontend), `stt` (Whisper speech-to-text), `agent-core` (Python agent querying Ollama directly).

## Step 1 — Build and start

```bash
# Via convenience script (from project root):
../scripts/launch/ollama-agent.sh

# Or directly (from tutorials/ directory):
docker compose -f ../docker/docker-compose.yml --profile ollama-agent up --build
```

First build takes ~5 minutes. After startup, you'll see:
- `ollama` downloading `llama3.2` (3B) on first run
- `ros2` starting all ROS 2 nodes: MoveIt motion planner, virtual scene, object spawner, rosbridge
- `agent-core` connecting to ROS 2 topics

## Step 2 — Verify it's running

```bash
docker compose -f ../docker/docker-compose.yml --profile ollama-agent ps
```

Expect these 5 services with `Up` status:

| Container | Status indicator | Purpose |
|-----------|-----------------|---------|
| `spatial_hmi_ollama` | `Up` (healthy) | LLM server with llama3.2. Must show `(healthy)` after the pull completes. |
| `spatial_hmi_ros2` | `Up` | ROS 2 Humble with all actuation nodes: MoveIt motion planner, virtual scene, object spawner, rosbridge, robot_state_publisher |
| `spatial_hmi_web` | `Up` | nginx serving the frontend at http://localhost:80 |
| `spatial_hmi_stt` | `Up` | Whisper tiny speech-to-text server for Firefox fallback |
| `spatial_hmi_agent_core` | `Up` | Python agent node subscribing to `/spatial_coords` and `/voice_commands` |

**Startup order:** `ollama` → `ros2` (waits for ollama healthy + model pulled) → `web` + `stt` → `agent-core`

**ROS 2 nodes running inside `spatial_hmi_ros2`:**

Each node prints a startup log. Verify with:

```bash
docker logs spatial_hmi_ros2 2>&1 | grep -E "\[INFO\].*started"
```

Expected output:

| Node | Log line | Purpose |
|------|----------|---------|
| `mock_motion_planning` | `[mock_motion_planning_node]: Mock Motion Planning Node started` | Subscribes `/target_goal`, plans via MoveIt 2, publishes `/joint_states` |
| `virtual_scene` | `[virtual_scene_node]: Virtual Scene Node started` | Publishes table/world markers on `/scene_markers` |
| `object_spawn` | `[object_spawn_node]: Object Spawn Node started` | Subscribes `/object_spawn`, looks up models, publishes MarkerArray |
| `rosbridge_websocket` | `[rosbridge_websocket]: Rosbridge WebSocket server started on port 9090` | WebSocket bridge for browser ↔ ROS 2 communication |
| `robot_state_publisher` | `[robot_state_publisher]: got segment base_link` | Loads URDF, publishes TF transforms for the arm model |

**Verify logs of each service:**

```bash
# Ollama — should show the launcher menu (server running underneath)
docker logs spatial_hmi_ollama 2>&1 | head -5

# ROS 2 — should show all 5 nodes started
docker logs spatial_hmi_ros2 2>&1 | grep "started"

# Agent core — should show startup message
docker logs spatial_hmi_agent_core
```

Then open http://localhost.

## Step 3 — Open the web UI

Navigate to http://localhost. You'll see:
- **Top left:** a 3D viewport with a simulated table, a robotic arm (orange), and a small green sphere at the base
- **Bottom:** camera feed, microphone transcript, and a text input box

## Step 4 — Grant permissions

- Click **Start Camera** → allow webcam access → a hand skeleton overlays on the camera feed when MediaPipe detects your hand
- Click **Start Mic** → allow microphone access → speech appears in the transcript box
- Or type commands directly in the text box and press Enter

## Step 5 — Try the "apple" scenario

These commands build on each other. Type each one in the text box and watch the 3D viewport respond.

| Command | What happens in the 3D view |
|---------|-----------------------------|
| *"create an apple at the middle"* | A red sphere (placeholder apple) appears on the table in the 3D view |
| *"move to the apple"* | The arm rotates and positions its gripper near the apple |
| *"grab"* | The gripper closes (visual feedback in the viewport) |
| *"move up"* | The arm lifts the apple upward |
| *"release"* | The gripper opens — apple stays at the new position |
| *"move left"* | The arm rotates to the left and stops |

Each command triggers the agent to publish a ROS 2 message. The arm in the 3D viewport updates in real time via rosbridge WebSocket.

## Step 6 — Watch the agent's reasoning (optional)

```bash
docker logs -f spatial_hmi_agent_core
```

You'll see the agent's full chain of thought — which prompt it selected, how it parsed the coordinates, and what action it decided to take.

## Step 7 — Stop

```bash
# Via convenience script:
../scripts/launch/stop.sh

# Or directly:
docker compose -f ../docker/docker-compose.yml --profile ollama-agent down
```
