# Tutorial 2: OpenClaw Agent

**What this launches:** 7 containers — `ollama`, `ros2`, `web`, `stt` (Whisper speech-to-text), plus `openclaw` (TypeScript agent framework Gateway), `perception-bridge` (Python forwarder + Node.js SDK bridge). This profile requires TypeScript compilation steps before first run.

## Step 1 — Build the TypeScript plugin and bridge

```bash
# Build the OpenClaw tool plugin
cd ../agents/openclaw_agent/plugin && npm install && npx tsc

# Build the perception forwarder bridge
cd ../bridge && npm install && npx tsc

# Return to project root
cd ../../..
```

## Step 2 — Build and start

```bash
# Via convenience script (from project root):
../scripts/launch/openclaw-agent.sh

# Or directly (from tutorials/ directory):
docker compose -f ../docker/docker-compose.yml --profile openclaw-agent up --build
```

First build takes ~6 minutes. After startup, you'll see:
- Same `ollama` + `ros2` + `web` as Tutorial 1
- `openclaw` Gateway listening on WebSocket port 1455
- `perception-bridge` connecting to rosbridge and forwarding perception data to the Gateway

## Step 3 — Verify

```bash
docker compose -f ../docker/docker-compose.yml --profile openclaw-agent ps
```

Expect these 6 services with `Up` status:

| Container | Status indicator | Purpose |
|-----------|-----------------|---------|
| `spatial_hmi_ollama` | `Up` (healthy) | LLM server with llama3.2 |
| `spatial_hmi_ros2` | `Up` | ROS 2 Humble with all actuation nodes |
| `spatial_hmi_web` | `Up` | nginx frontend at http://localhost:80 |
| `spatial_hmi_openclaw` | `Up` | OpenClaw Gateway with tool plugin, listening on WebSocket port 1455 |
| `spatial_hmi_perception_bridge` | `Up` | Forwarder relaying `/spatial_coords` and `/voice_commands` to the Gateway |
| `spatial_hmi_agent_core` *(not present)* | — | Does not run in this profile (only `ollama-agent` and `all` profiles include it) |

**Startup order:** `ollama` → `ros2` → `web` + `openclaw` → `perception-bridge`

**ROS 2 nodes running inside `spatial_hmi_ros2`:**

```bash
docker logs spatial_hmi_ros2 2>&1 | grep -E "\[INFO\].*started"
```

| Node | Log line | Purpose |
|------|----------|---------|
| `mock_motion_planning` | `[mock_motion_planning_node]: Mock Motion Planning Node started` | Subscribes `/target_goal`, plans via MoveIt 2, publishes `/joint_states` |
| `virtual_scene` | `[virtual_scene_node]: Virtual Scene Node started` | Publishes table/world markers on `/scene_markers` |
| `object_spawn` | `[object_spawn_node]: Object Spawn Node started` | Subscribes `/object_spawn`, looks up models, publishes MarkerArray |
| `rosbridge_websocket` | `[rosbridge_websocket]: Rosbridge WebSocket server started on port 9090` | WebSocket bridge for browser ↔ ROS 2 communication |
| `robot_state_publisher` | `[robot_state_publisher]: got segment base_link` | Loads URDF, publishes TF transforms for the arm model |

**Verify logs of each service:**

```bash
# Ollama — server running
docker logs spatial_hmi_ollama 2>&1 | head -3

# ROS 2 — all 4 actuation nodes started
docker logs spatial_hmi_ros2 2>&1 | grep "started"

# OpenClaw Gateway
docker logs spatial_hmi_openclaw 2>&1 | head -10

# Perception bridge
docker logs spatial_hmi_perception_bridge 2>&1 | head -5
```

Open http://localhost.

## Step 4 — Try a full scene interaction

The 3D viewport shows a simulated table with the robotic arm. Type or say these commands:

| Command | What happens |
|---------|-------------|
| *"create a mug at the middle"* | A purple sphere (placeholder mug) appears on the table |
| *"move to the mug"* | The arm rotates and reaches toward the mug |
| *"grab"* | Gripper closes — the mug is now attached to the arm tip |
| *"move right"* | The arm swings to the right, carrying the mug |
| *"place it on the table"* | The arm lowers and releases the mug at the new spot |
| *"create an apple at the left"* | A red sphere appears to the left of the mug |
| *"move to the apple and grab it"* | The arm moves to the apple and closes its gripper |

**OpenClaw-specific:** Run `docker logs -f spatial_hmi_openclaw` in another terminal to see the Gateway's tool-call decisions — the LLM chooses between `arm_move`, `arm_grasp`, `arm_release`, and `spawn_object` tools.

## Step 5 — Test object spawning with Sketchfab (optional)

Set your Sketchfab API key before starting:

```bash
SKETCHFAB_API_KEY=your_key_here \
  docker compose -f ../docker/docker-compose.yml --profile openclaw-agent up
```

Then say *"create a chair at the middle"* — the OpenClaw agent spawns it via the fallback download.

## Step 6 — Switch backend transport (optional)

The perception forwarder defaults to the Node.js SDK bridge. To use the direct Python WebSocket backend instead:

```bash
OPENCLAW_FORWARDER_BACKEND=websocket \
  docker compose -f ../docker/docker-compose.yml --profile openclaw-agent up
```

## Step 7 — Stop

```bash
# Via convenience script:
../scripts/launch/stop.sh

# Or directly:
docker compose -f ../docker/docker-compose.yml --profile openclaw-agent down
```
