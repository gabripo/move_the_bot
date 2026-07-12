# Test Strategy — Spatial HMI Robotics

## Test Levels

```
┌──────────────────────────────┐
│  E2E (full Docker stack)     │  ← 1 test: full_pipeline
├──────────────────────────────┤
│  Integration (components)    │  ← 4 tests: rosbridge, topic pipeline,
│                              │            perception forwarder (×2 backends)
├──────────────────────────────┤
│  Unit (pure functions)       │  ← 3 tests: IK solver, model lookup,
│                              │            agent protocol parsing
└──────────────────────────────┘
```

## 1. Unit Tests

### 1.1 IK Solver (`tests/unit/test_ik_solver.py`)

Tests for `mock_kinematics_node.inverse_kinematics(x, y, z)`:

| Test case | Input | Expected |
|-----------|-------|----------|
| Forward reachable point | (0.2, 0.0, 0.3) | Returns (θ1,θ2,θ3) tuple |
| Symmetric point | (0.0, 0.2, 0.2) | θ1 ≈ π/2 |
| Low point | (0.15, 0.0, 0.05) | Valid angles, all within joint limits |
| High point | (0.1, 0.0, 0.45) | Valid angles, elbow relatively straight |
| Unreachable (too far) | (0.8, 0.0, 0.8) | Returns `None` |
| Unreachable (too close) | (0.01, 0.0, 0.01) | Returns `None` |
| Origin | (0.0, 0.0, 0.0) | Returns `None` (below base) |
| Negative x | (-0.2, 0.1, 0.2) | θ1 negative, valid angles |
| Forward/IK roundtrip | random valid point | FK(IK(p)) ≈ p (within 1mm) |
| Joint limit violation | (0.0, 0.5, 0.0) | All joint angles within [-π, π] |

### 1.2 Model Lookup (`tests/unit/test_model_lookup.py`)

Tests for `models/lookup.lookup(object_name)`:

| Test case | Input | Expected |
|-----------|-------|----------|
| Builtin hit | "apple" | Returns (builtin path, "builtin") |
| Builtin hit (case insensitive) | "Apple" | Returns (builtin path, "builtin") |
| Builtin hit (alias) | "coffee mug" | Returns (mug.glb path, "builtin") |
| Builtin hit (alias) | "ball" | Returns (sphere.glb path, "builtin") |
| Cache hit | Already downloaded "unicorn" | Returns (cached path, "cache") |
| Sketchfab hit (mock) | "teapot" (with API key mock) | Returns (cached path, "sketchfab") |
| Sketchfab no results (mock) | "xyznonexistent123" (with API key mock) | Returns `None` |
| No API key configured | "teapot" (without API key) | Returns `None` |
| Empty string | "" | Returns `None` |

### 1.3 Agent Protocol Parsing (`tests/unit/test_agent_protocol.py`)

Tests for JSON action parsing and validation:

| Test case | Input | Expected |
|-----------|-------|----------|
| Valid move_to | `{"action":"move_to","target":{"x":0.1,"y":0.2,"z":0.3}}` | Parsed correctly, all fields present |
| Valid grasp | `{"action":"grasp"}` | Parsed correctly |
| Valid spawn | `{"action":"spawn","object":"apple","target":{"x":0.2,"y":0.0,"z":0.05}}` | Parsed correctly |
| Invalid JSON | `not json` | Error raised |
| Missing action field | `{"x":1}` | Error raised |
| Unknown action | `{"action":"fly"}` | Error raised |
| Out-of-bounds target | `{"action":"move_to","target":{"x":2.0,"y":0.0,"z":0.0}}` | Error raised (validation) |
| Missing fields in target | `{"action":"move_to","target":{"x":1}}` | Error raised (validation) |

## 2. Integration Tests

### 2.1 rosbridge Communication (`tests/integration/test_rosbridge_comm.py`)

Requires a running rosbridge server (spawned in test container).

| Test case | Steps |
|-----------|-------|
| WebSocket connect | Connect to `ws://localhost:9090` → verify "connected" |
| Publish Point | Publish to `/test_point` with values → verify via ROS 2 subscriber |
| Publish String | Publish to `/test_string` → verify via ROS 2 subscriber |
| Subscribe JointState | Subscribe to `/joint_states` → wait for message → verify structure |
| Subscribe MarkerArray | Subscribe to `/virtual_scene` → wait for message → verify structure |
| Roundtrip latency | Measure time from publish → subscriber receipt (should be <100ms) |

### 2.2 Topic Pipeline (`tests/integration/test_topic_pipeline.py`)

Requires a running ROS 2 stack with all nodes.

| Test case | Steps |
|-----------|-------|
| Hand coords → joint_states | Publish `/spatial_coords` → agent decides → `/target_goal` → IK → `/joint_states`. Verify joint_states updated within 2s. |
| Voice command → grasp | Publish `/voice_commands` "grab" → verify `/grasp_command` published with "grasp" |
| Voice command → release | Publish `/voice_commands` "release" → verify `/grasp_command` published with "release" |
| Voice command → spawn | Publish `/voice_commands` "create apple at middle" → verify `/object_spawn` published with correct JSON |
| Unreachable target | Publish `/spatial_coords` to far away point → agent should NOT publish `/target_goal` (or publish at limits) |

### 2.3 Perception Forwarder (`tests/integration/test_perception_forwarder.py`)

Tests both backends: `sdk` and `websocket`.

| Test case | Steps |
|-----------|-------|
| SDK backend: forward coords | Set `OPENCLAW_FORWARDER_BACKEND=sdk`. Publish `/spatial_coords`. Verify bridge process received JSON on stdin. |
| SDK backend: forward voice | Publish `/voice_commands`. Verify bridge process received JSON. |
| SDK backend: process lifecycle | Start/stop forwarder, verify bridge process starts/stops. |
| WS backend: forward coords | Set `OPENCLAW_FORWARDER_BACKEND=websocket`. Publish `/spatial_coords`. Verify WebSocket message sent. |
| WS backend: reconnect | Simulate network drop → verify auto-reconnect. |

### 2.4 Object Spawn (`tests/integration/test_object_spawn.py`)

| Test case | Steps |
|-----------|-------|
| Spawn builtin object | Publish `/object_spawn` with builtin model → verify Marker in `/virtual_scene` |
| Spawn cached object | Publish `/object_spawn` with cached path → verify Marker appears |
| Spawn unknown object | Publish `/object_spawn` with nonexistent path → verify no Marker |
| Spawn position | Publish with (0.3, 0.2, 0.1) → verify Marker pose matches |

## 3. End-to-End Tests

### 3.1 Full Pipeline (`tests/e2e/test_full_pipeline.py`)

Uses `docker-compose.test.yml` that starts minimal services:
- ros2 (rosbridge + actuation nodes)
- agent-core (Ollama direct agent, with mock Ollama that returns canned JSON)
- web (nginx)

| Test case | Steps |
|-----------|-------|
| Hand tracking → arm move | Connect to rosbridge → publish `/spatial_coords` (0.2, 0.3, 0.4) + `/voice_commands` "move there" → wait 3s → assert `/joint_states` changed from initial |
| Voice grab → grasp + move | Publish "pick that up" → assert `/grasp_command` "grasp" published |
| Spawn object | Publish "create an apple at the middle" → assert `/object_spawn` published with apple in JSON |
| Text input (same as voice) | Publish text via `/voice_commands` → same assertions as voice |
| Multiple objects | Spawn apple + mug → verify two Markers in scene |
| Unknown object | Publish "create a unicorn" → system reports error (no model found) |

## 4. Test Infrastructure

### Docker Compose Test Profile

`docker-compose.test.yml`:
```yaml
services:
  ros2:
    build: { context: ., dockerfile: docker/Dockerfile.ros2 }
    command: >
      bash -c "source /opt/ros/humble/setup.bash &&
               source /ros_ws/install/setup.bash &&
               ros2 launch mock_hmi_core deploy.launch.py"

  bridge:
    image: ros:humble-ros-base
    command: >
      bash -c "source /opt/ros/humble/setup.bash &&
               ros2 run rosbridge_server rosbridge_websocket"
    ports: ["9090:9090"]

  agent-mock:
    build: ./agents/agent_core
    environment:
      - OLLAMA_URL=http://mock-ollama:5000/generate
    depends_on: [ros2]

  mock-ollama:
    image: python:3.12-slim
    command: python -m http.server 5000  # returns canned JSON responses
    volumes:
      - ./tests/fixtures/ollama-mock:/app
    working_dir: /app
```

### Test Fixtures

`tests/conftest.py` shared fixtures:
- `ros_bridge`: WebSocket connection to rosbridge
- `mock_openclaw_gateway`: Echo WebSocket server for forwarder tests
- `test_glb_factory`: Creates minimal valid GLB files for tests
- `ollama_mock`: HTTP server returning canned JSON responses

### Running Tests

```bash
# Unit tests (no Docker needed)
pytest tests/unit/

# Integration tests (requires Docker stack)
docker compose -f docker-compose.test.yml up -d
pytest tests/integration/
docker compose -f docker-compose.test.yml down

# E2E tests
docker compose -f docker-compose.test.yml up --abort-on-container-exit --build
```

## 5. CI Integration (future)

```yaml
# .github/workflows/test.yml (for reference)
name: Test
on: [push, pull_request]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install pytest && pytest tests/unit/

  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose -f docker-compose.test.yml up --abort-on-container-exit --build
```
