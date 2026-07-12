# Tutorial 3: Both Agents

**What this launches:** All 7 containers. Both agents run simultaneously and both publish to the same ROS 2 topics. Only one agent should actuate at a time (they share the same topic bus).

## Step 1 — Build dependencies

```bash
# Build OpenClaw TypeScript (if not already done)
cd ../agents/openclaw_agent/plugin && npm install && npx tsc
cd ../bridge && npm install && npx tsc
cd ../../..
```

## Step 2 — Build and start

```bash
# Via convenience script (from project root):
../scripts/launch/all.sh

# Or directly (from tutorials/ directory):
docker compose -f ../docker/docker-compose.yml --profile all up --build
```

Takes ~7 minutes. Both `agent-core` and `openclaw` connect to the same ROS 2 topics.

## Step 3 — Verify

```bash
docker compose -f ../docker/docker-compose.yml --profile all ps
```

Expect these 6 services with `Up` status:

| Container | Status indicator | Purpose |
|-----------|-----------------|---------|
| `spatial_hmi_ollama` | `Up` (healthy) | LLM server with llama3.2 |
| `spatial_hmi_ros2` | `Up` | ROS 2 Humble with all actuation nodes |
| `spatial_hmi_web` | `Up` | nginx frontend at http://localhost:80 |
| `spatial_hmi_agent_core` | `Up` | Ollama direct agent (profile `ollama-agent`) |
| `spatial_hmi_openclaw` | `Up` | OpenClaw Gateway (profile `openclaw-agent`) |
| `spatial_hmi_perception_bridge` | `Up` | Forwarder relaying perception data to the Gateway |

**Startup order:** `ollama` → `ros2` → `web` + `agent-core` + `openclaw` → `perception-bridge`

**Verify logs:**

```bash
# All six containers are running
docker ps --filter name=spatial_hmi --format "table {{.Names}}\t{{.Status}}"

# Each agent should show its startup message
docker logs spatial_hmi_agent_core
docker logs spatial_hmi_openclaw 2>&1 | head -5
```

Open http://localhost.

## Step 4 — Compare agents side-by-side

Two agents are listening to the same topics. Open two log terminals to compare:

```bash
# Terminal 1 — Ollama direct agent
docker logs -f spatial_hmi_agent_core

# Terminal 2 — OpenClaw agent
docker logs -f spatial_hmi_openclaw
```

## Step 5 — Try commands and watch both agents react

Type commands in the web UI text box. Both agents receive the same input, but only one response will win (last publish wins on the same topic).

| Command | Watch in 3D view | Watch in logs |
|---------|------------------|---------------|
| *"create an apple at the middle"* | Red sphere appears on the table | Both agents print their parsed intent; whichever publishes last places the apple |
| *"move to the apple"* | Arm rotates toward the apple | Compare how each agent formulates the `/target_goal` coordinates |
| *"grab"* | Gripper closes | Direct agent sends `/grasp_command` directly; OpenClaw invokes the `arm_grasp` tool |
| *"create a bottle at the right"* | Blue sphere appears on the right | Both agents receive `/voice_commands` and independently decide to publish `/object_spawn` |

The logs show the different reasoning paths: the direct agent uses a single prompt with action selection, while OpenClaw routes through tool definitions with structured schemas.

## Step 6 — Stop

```bash
# Via convenience script:
../scripts/launch/stop.sh

# Or directly:
docker compose -f ../docker/docker-compose.yml --profile all down
```
