# Architecture Plan — Spatial HMI Robotics

## System Overview

An AI-powered spatial human-machine interface: webcam + microphone capture user input, MediaPipe + Web Speech API process them in-browser, an AI agent reasons about actions (Ollama direct OR OpenClaw), and a simulated 3-DOF robotic arm is rendered in Three.js and RViz2.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  BROWSER (user device)                                                       │
│                                                                              │
│  ┌─────────────────────┐   ┌──────────────────────┐   ┌─────────────────┐  │
│  │  MediaPipe Hands    │   │  Web Speech API      │   │  Text Input     │  │
│  │  (camera → hand     │   │  (mic → voice text)  │   │  (type commands)│  │
│  │   landmarks)        │   └──────────┬───────────┘   └────────┬────────┘  │
│  └─────────┬───────────┘              │                         │           │
│            │                          └──────────┬──────────────┘           │
│            │                          publish to /voice_commands            │
│            │  publish to /spatial_coords                                    │
│            ▼                          ▼                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  roslibjs (rosbridge WebSocket client)                                │  │
│  │  ├── publish: /spatial_coords, /voice_commands                       │  │
│  │  ├── subscribe: /joint_states, /object_spawn                         │  │
│  │  └── Three.js renderer + GLTF Loader for spawned objects            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │  WebSocket (ws://host/ws/)
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  DOCKER HOST                                                                 │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  web container (nginx:alpine) :80                                      │  │
│  │  ├── Serves static frontend from /usr/share/nginx/html                │  │
│  │  ├── /ws/ → proxy_pass http://ros2:9090 (WebSocket upgrade)           │  │
│  │  └── /stt/ → proxy_pass http://stt:8000 (speech-to-text)              │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                    │                                          │
│                                    ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  stt container (Whisper tiny + FastAPI) :8000                           │  │
│  │  └── POST /transcribe → Whisper model → {"text": "..."}                │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                    │                                          │
│                                    ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  ROS 2 TOPIC BUS (the formal Agent Protocol interface)                 │  │
│  │                                                                        │  │
│  │  Input topics:                                                         │  │
│  │    /spatial_coords  (geometry_msgs/Point)  — hand landmark midpoint    │  │
│  │    /voice_commands  (std_msgs/String)       — transcribed speech/text  │  │
│  │                                                                        │  │
│  │  Output topics:                                                        │  │
│  │    /target_goal     (geometry_msgs/Point)  — target position for arm   │  │
│  │    /grasp_command   (std_msgs/String)       — "grasp" / "release"      │  │
│  │    /object_spawn    (std_msgs/String)       — JSON: {name,path,x,y,z}  │  │
│  │    /joint_states    (sensor_msgs/JointState) — computed joint angles   │  │
│  │    /virtual_scene   (visualization_msgs/MarkerArray) — scene markers   │  │
│  └────────────┬───────────────────────────────────────────────────────────┘  │
│               │                                                              │
│   ┌───────────┴───────────┐                          ┌────────────────────┐  │
│   │  AGENT: ollama-agent  │                          │  AGENT: openclaw   │  │
│   │  (profile: default)   │                          │  (profile: opt-in) │  │
│   │                       │                          │                    │  │
│   │  agentic_core_node.py │                          │  OpenClaw Gateway  │  │
│   │  ┌──────────────────┐ │                          │  (Node.js)         │  │
│   │  │ Ollama HTTP API  │ │                          │  ┌──────────────┐  │  │
│   │  │ → llama3.2       │ │                          │  │ Tool plugin  │  │  │
│   │  └──────────────────┘ │                          │  │ arm_move     │  │  │
│   │  sub /spatial_coords  │                          │  │ arm_grasp    │  │  │
│   │  sub /voice_commands  │                          │  │ arm_release  │  │  │
│   │  pub /target_goal     │                          │  │ spawn_object │  │  │
│   │  pub /grasp_command   │                          │  └──────────────┘  │  │
│   └───────────────────────┘                          └────────┬───────────┘  │
│                                                               │              │
│                                              ┌────────────────┴──────────┐  │
│                                              │  perception_forwarder.py   │  │
│                                              │  (sub /spatial_coords,     │  │
│                                              │       /voice_commands      │  │
│                                              │   → stdin → Node.js bridge)│  │
│                                              │                            │  │
│                                              │  OR (env var):             │  │
│                                              │  perception_forwarder_ws.py│  │
│                                              │  (direct Python WebSocket  │  │
│                                              │   → Gateway Protocol)      │  │
│                                              └────────────────────────────┘  │
│                                                               │              │
│                                              ┌────────────────┴──────────┐  │
│                                              │  forwarder_bridge.ts      │  │
│                                              │  (Node.js, openclaw-sdk)  │  │
│                                              │  stdin → openclaw-sdk →   │  │
│                                              │  OpenClaw Gateway          │  │
│                                              └────────────────────────────┘  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  ROS 2 ACTUATION NODES (ros2 container)                               │  │
│  │                                                                        │  │
│  │  ┌─────────────────────┐  ┌──────────────────────┐  ┌───────────────┐  │  │
│  │  │ mock_kinematics_node│  │ virtual_scene_node    │  │ object_spawn  │  │  │
│  │  │ sub /target_goal    │  │ pub /virtual_scene   │  │ _node         │  │  │
│  │  │ sub /grasp_command  │  │ (coffee mug, table,  │  │ sub /object_  │  │  │
│  │  │ pub /joint_states   │  │  etc. markers)        │  │   spawn       │  │  │
│  │  │ (3-DOF IK solver)   │  └──────────────────────┘  │ lookup model  │  │  │
│  │  └─────────────────────┘                             │ → MarkerArray │  │  │
│  │                                                      └───────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  ollama container                                                      │  │
│  │  └── llama3.2 model (host.docker.internal:11434 inside docker)         │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │  models/ (shared volume)                                               │  │
│  │  ├── builtin/  (bundled .glb files, read-only)                        │  │
│  │  ├── cache/    (Sketchfab downloads, writable)                         │  │
│  │  └── lookup.py (lookup API)                                            │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Perception → Agent → Actuation

```
Camera  ─→ MediaPipe ─→ hand landmarks (x,y,z) ─→ /spatial_coords
Mic     ─→ Web Speech ─→ "pick up the mug"      ─→ /voice_commands  (Chrome/Safari)
Mic     ─→ MediaRecorder ─→ webm blob ─→ stt:8000/transcribe ─→ /voice_commands  (Firefox)
Text    ─→ form input ─→ "create apple at 0.2,0,0.05" ─→ /voice_commands

Agent subscribes to both input topics:

[Ollama Direct]:
  /spatial_coords + /voice_commands → prompt llama3.2 → JSON action
  → /target_goal  or  /grasp_command  or  /object_spawn

[OpenClaw]:
  perception_forwarder → (SDK|WS) → OpenClaw Gateway → LLM reasoning
  → Tool calls → rosbridge → /target_goal  or  /grasp_command  or  /object_spawn

Actuation:
  /target_goal → mock_kinematics_node → IK solver → /joint_states
  /grasp_command → mock_kinematics_node → gripper state
  /object_spawn → object_spawn_node → load GLB → /virtual_scene (MarkerArray)

Visualization:
  /joint_states → Three.js (roslibjs) → arm model animates
  /joint_states → RViz2 (with robot_state_publisher) → URDF arm
  /object_spawn → Three.js (GLTFLoader) → 3D object appears
```

## Agent Protocol (formal contract)

The interface between any agent and the rest of the system is defined solely by ROS 2 topic types and semantics:

| Direction | Topic | Type | Semantics |
|-----------|-------|------|-----------|
| Input | `/spatial_coords` | `geometry_msgs/Point` | Midpoint of index fingertip and thumb tip (MediaPipe hand tracking). x,y,z in meters. |
| Input | `/voice_commands` | `std_msgs/String` | Transcribed speech OR typed text prompt. Arbitrary natural language. |
| Output | `/target_goal` | `geometry_msgs/Point` | Target position for arm end-effector. Published by agent after reasoning. |
| Output | `/grasp_command` | `std_msgs/String` | `"grasp"` or `"release"`. |
| Output | `/object_spawn` | `std_msgs/String` | JSON: `{"name":"apple","path":"/models/cache/abc.glb","x":0.2,"y":0.0,"z":0.05}` |

**To add a new agent implementation:**
1. Subscribe to `/spatial_coords` and `/voice_commands`
2. Process with any LLM/framework
3. Publish to `/target_goal`, `/grasp_command`, `/object_spawn` as needed
4. Add a Docker Compose profile and container
5. Done — no other system changes required

## Service Topology (Docker Compose)

```yaml
Services:
  ollama:     always running
  ros2:       always running  (contains all ROS 2 nodes)
  web:        always running  (nginx + static frontend)
  stt:        always running  (Whisper tiny + FastAPI speech-to-text)

  agent-core:      profile [ollama-agent, all]  (Ollama direct agent)
  openclaw:        profile [openclaw-agent, all] (OpenClaw Gateway)
  perception-bridge: profile [openclaw-agent, all] (forwarder + bridge)
```

## NemoClaw Migration Path

To migrate from OpenClaw to NemoClaw:
1. Replace the `openclaw` container image with `nvidia/nemoclaw:latest`
2. Change `OPENCLAW_GATEWAY_URL` from `ws://openclaw:1455` to `ws://nemoclaw:1455`
3. The `openclaw-sdk` and Gateway Protocol are identical — no code changes in `perception_forwarder.py` or `forwarder_bridge.ts`
4. Add NemoClaw-specific security policies (OpenShell YAML)
