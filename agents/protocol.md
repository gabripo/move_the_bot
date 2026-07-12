# Agent Protocol — Spatial HMI Robotics

## Contract

The interface between any agent implementation and the rest of the system is
defined **solely by ROS 2 topic types and semantics**. This ensures agents are
hot-swappable without modifying perception or actuation code.

## Input Topics (agent subscribes)

| Topic | Type | Frequency | Semantics |
|-------|------|-----------|-----------|
| `/spatial_coords` | `geometry_msgs/Point` | ~30 Hz | Midpoint of index fingertip and thumb tip from MediaPipe hand tracking. Values are in meters, scaled to robot workspace. |
| `/voice_commands` | `std_msgs/String` | Event-driven | Natural language text from speech recognition OR typed text input. Both modalities publish to the same topic. |

## Output Topics (agent publishes)

| Topic | Type | Semantics |
|-------|------|-----------|
| `/target_goal` | `geometry_msgs/Point` | Target (x,y,z) for the arm end-effector. The kinematics node computes inverse kinematics to reach this position. |
| `/grasp_command` | `std_msgs/String` | `"grasp"` to close gripper, `"release"` to open. |
| `/object_spawn` | `std_msgs/String` | JSON string: `{"name":"<object_name>","path":"<glb_path>","x":<float>,"y":<float>,"z":<float>}`. Triggers the object_spawn_node to load the GLB model and publish a MarkerArray. |

## How to add a new agent

1. Create a new directory under `agents/` (e.g., `agents/my_agent/`)
2. Implement a ROS 2 node (Python, C++, or any language with ROS 2 bindings) that:
   - Subscribes to `/spatial_coords` and `/voice_commands`
   - Processes them with your chosen AI/LLM
   - Publishes actions to `/target_goal`, `/grasp_command`, `/object_spawn`
3. Add a Dockerfile and container to `docker/docker-compose.yml` with a new profile
4. Document the agent in this directory

## Available implementations

| Agent | Profile | Language | Description |
|-------|---------|----------|-------------|
| `agent_core/` | `ollama-agent` | Python | Direct Ollama HTTP API with llama3.2. Simple, single-process. |
| `openclaw_agent/` | `openclaw-agent` | TypeScript + Python | Full OpenClaw Gateway with tool plugin. Supports NemoClaw migration. |
