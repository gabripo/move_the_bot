# Design Choices — Spatial HMI Robotics

## 1. ROS 2 on macOS via Docker (not native)

**Decision:** Run ROS 2 Humble inside Docker with `osrf/ros:humble-desktop`.

**Rationale:** ROS 2 Humble is not officially supported on macOS. Docker provides a clean, reproducible environment. The `-desktop` variant includes RViz2. X11 forwarding enables RViz2 GUI display when desired.

## 2. Host-side Perception (MediaPipe + Web Speech) in Browser

**Decision:** Camera capture, hand tracking, and speech recognition all run in the user's browser, not on the server.

**Rationale:** 
- macOS `/dev/video0` is unavailable inside Docker
- MediaPipe Tasks Vision runs efficiently in-browser via WebGL
- Web Speech API is built into Chrome/Safari — no Whisper model deployment needed
- Only lightweight landmark coordinates (63 floats) are sent over the network, not video frames
- Enables deployment to cloud hosting platforms (browser provides hardware access)

## 3. rosbridge WebSocket for all host↔ROS communication

**Decision:** `rosbridge_server` on port 9090 with WebSocket transport.

**Rationale:** Clean separation of concerns. The browser (roclibjs), Python scripts, and Node.js services all communicate through a single protocol. Nginx reverse proxy handles WebSocket upgrade at `/ws/`.

## 4. Natural Language via LLM (not keyword matching)

**Decision:** Voice commands and text prompts are interpreted by an LLM (llama3.2 via Ollama).

**Rationale:** Enables flexible commands like "move a bit to the left," "pick up the mug and place it on the table," "create an apple at the middle." LLM outputs structured JSON actions rather than requiring rigid keyword grammars.

## 5. Two Agent Implementations (hot-swappable via Docker Compose profiles)

**Decision:** Both `agentic_core_node.py` (Ollama direct) and OpenClaw-based agent are available, selectable via Docker Compose profiles.

**Rationale:**
- Ollama direct: simple, single-container, minimal dependencies — good for local dev and testing
- OpenClaw: full agent framework with memory, multi-channel support, tool sandboxing — good for production and real hardware migration
- Profiles allow the user to choose without modifying configuration files

## 6. Perception Forwarder: SDK primary, WebSocket fallback

**Decision:** `perception_forwarder.py` uses `openclaw-sdk` (Node.js) via a stdin/stdout bridge process by default. A direct Python WebSocket implementation (`perception_forwarder_ws.py`) is available via `OPENCLAW_FORWARDER_BACKEND=websocket`.

**Rationale:**
- `openclaw-sdk` is the official, supported, type-safe integration path — handles reconnection, auth, and protocol versioning
- Direct WebSocket is lighter (no Node.js dependency) and demonstrates the Gateway protocol for NemoClaw compatibility
- Both share the same ROS 2 subscription logic; only the output transport differs

## 7. 3D Model Database: Builtin cache primary, Sketchfab fallback

**Decision:** A bundled set of `.glb` files serves common objects (apple, mug, bottle, cube, sphere, table). Sketchfab Download API acts as fallback for uncommon objects.

**Rationale:**
- Bundled models are instantly available, no API key needed, no network latency
- Sketchfab provides 1M+ free models for long-tail queries
- Sketchfab requires an API key (stored as secret); if unset, only builtin models are available
- Failed lookups (model not found) are reported back to the user — no silent failures

## 8. Three.js + GLTF Loader for Web Visualization

**Decision:** Three.js with `GLTFLoader` for rendering both the robotic arm and spawned 3D objects.

**Rationale:** Three.js is the de-facto standard for browser 3D. GLTF/GLB is the industry standard format for 3D assets. `GLTFLoader` loads both bundled and Sketchfab-downloaded models. OrbitalControls provides intuitive camera manipulation.

## 9. Analytical IK (3-DOF, closed-form)

**Decision:** Closed-form inverse kinematics for a 3-revolute-joint arm (base rotation, shoulder, elbow).

**Rationale:** Deterministic, no numerical iteration, O(1) computation. Sufficient for a mock simulation. The IK solver is a pure function (`inverse_kinematics(x,y,z) → (θ1,θ2,θ3)`) — easy to unit test and replace with a real MoveIt-based solver later.

## 10. Single ROS 2 Container (not multi-container DDS)

**Decision:** All ROS 2 nodes run in a single container.

**Rationale:** ROS 2 DDS relies on UDP multicast for discovery, which doesn't work reliably across Docker Compose services. A single container avoids DDS networking issues entirely. rosbridge_server (WebSocket) provides the external interface.

## 11. Prompts stored as Markdown files

**Decision:** All LLM system prompts, skill definitions, and instructions are stored in `PLAN_PROMPTS.md` and in `agents/*/prompts/*.md`.

**Rationale:** Prompts are first-class artifacts. Storing them in Markdown makes them version-controlled, reviewable, and shareable. They can be fed directly to AI agentic coding tools.

## 12. Tests at multiple levels

**Decision:** Unit tests, integration tests (rosbridge, topic pipeline, perception forwarder), and E2E tests.

**Rationale:** The communication stack (browser → rosbridge → ROS 2 → agent → ROS 2 → visualization) has many moving parts. Isolating each layer with tests ensures failures are caught early and the system remains maintainable as it grows.

## 13. Server-side Whisper for Firefox (not client-side Transformers.js)

**Decision:** Speech-to-text for Firefox uses a server-side Whisper tiny model in a dedicated Docker container (`stt`), accessed via HTTP POST through nginx proxy. Chrome/Safari continue using the native Web Speech API.

**Rationale:**
- Firefox lacks native `SpeechRecognition` (Chrome/Safari have `webkitSpeechRecognition`)
- Client-side Transformers.js + Whisper via `import()` had persistent dependency/CORS/compatibility issues on Firefox — ES module loading, SharedArrayBuffer requirements, Hugging Face hub fetch rules, and ONNX runtime WASM initialization all caused failures
- A server-side FastAPI container with `openai-whisper` tiny model is simpler to deploy, has no browser compatibility issues, downloads the model once during Docker build, and uses standard HTTP POST for audio upload
- Audio capture uses the standard `MediaRecorder` API (supported by all browsers) and sends the `.webm` blob to the server via `fetch()` — works in Firefox, Chrome, and Safari
- The small Whisper tiny model (~150MB) runs adequately fast on CPU for short voice commands (2–5s of audio → 3–10s transcription on Docker amd64 emulation)
