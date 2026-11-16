import { HandControl, fakeHand } from "./hand.js";
import { Recording } from "./recording.js";
import { Scanner } from "./scan.js";
import { Ros } from "./ros.js";
import { Speech } from "./speech.js";
import { Viewer } from "./viewer.js";

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const wsUrl = params.get("ws")
  || `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${location.pathname.replace(/[^/]*$/, "")}ws/`;

const ros = new Ros(wsUrl);
let rec = null;                 // recording mode (?rec), set up at the end
const viewer = new Viewer($("viewer"));
// Handles for automated tests and for recording demos without a camera (filled in below).
window.mtb = { ros, viewer, objects: [], state: {}, agent: {} };
viewer.loadRobot("./robot/so101.urdf").catch((e) => addEntry("error", `Could not load the robot model: ${e.message || e}`));

$("views").addEventListener("click", (event) => {
  const view = event.target.dataset.view;
  if (!view) return;
  viewer.setView(view);
  for (const b of $("views").children) b.setAttribute("aria-pressed", b === event.target ? "true" : "false");
});

// ------------------------------------------------------------ conversation

function addEntry(role, text) {
  const log = $("log");
  const entry = document.createElement("div");
  entry.className = `entry ${["user", "robot", "info", "error"].includes(role) ? role : "info"}`;
  entry.textContent = text;
  log.appendChild(entry);
  while (log.children.length > 200) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
}

function send(text) {
  text = text.trim();
  if (!text) return;
  if (!ros.string("/voice_commands", text)) {
    addEntry("error", "Not connected to the robot yet.");
  }
}

$("command-form").addEventListener("submit", (event) => {
  event.preventDefault();
  rec?.source($("command").value, "text");
  send($("command").value);
  $("command").value = "";
});
$("examples").addEventListener("click", (event) => {
  if (event.target.tagName === "BUTTON") send(event.target.textContent);
});
$("btn-home").addEventListener("click", () => send("go home"));
$("btn-clear").addEventListener("click", () => send("clear the table"));
$("btn-stop").addEventListener("click", () => send("stop"));

ros.subscribe("/agent_log", "std_msgs/String", (msg) => {
  try {
    const entry = JSON.parse(msg.data);
    addEntry(entry.role, entry.text);
  } catch { addEntry("info", msg.data); }
}, { queue: 100 });

// ----------------------------------------------------------------- status

const pill = (id, state, text) => {
  const el = $(id);
  el.className = `pill ${state}`;
  if (text) el.textContent = text;
};
let lastRobotState = 0;
let robotReady = false;

ros.onStatus((connected) => {
  pill("pill-ros", connected ? "ok" : "off", connected ? "Connected" : "Offline");
  if (!connected) { pill("pill-robot", "off", "Robot"); pill("pill-llm", "", "Model"); }
});
setInterval(() => {
  if (ros.connected && Date.now() - lastRobotState > 3000) pill("pill-robot", "wait", "Robot starting");
}, 1000);

ros.subscribe("/joint_states", "sensor_msgs/JointState", (msg) => viewer.setJoints(msg.name, msg.position), { throttle: 33 });
ros.subscribe("/scene/objects", "std_msgs/String", (msg) => {
  try {
    window.mtb.objects = JSON.parse(msg.data).objects || [];
    viewer.setObjects(window.mtb.objects);
  } catch (e) { console.error("scene update failed", e); }
}, { latched: true });

ros.subscribe("/skill/state", "std_msgs/String", (msg) => {
  let state;
  try { state = JSON.parse(msg.data); } catch { return; }
  lastRobotState = Date.now();
  robotReady = !!state.ready;
  window.mtb.state = state;
  pill("pill-robot", state.ready ? "ok" : "wait", state.ready ? "Robot ready" : "Robot starting");
  $("fact-holding").textContent = state.holding || "nothing";
  if (state.tool) {
    $("fact-tool").textContent = `x ${state.tool[0].toFixed(2)}  y ${state.tool[1].toFixed(2)}  z ${state.tool[2].toFixed(2)} m`;
  }
});

ros.subscribe("/agent/state", "std_msgs/String", (msg) => {
  let state;
  try { state = JSON.parse(msg.data); } catch { return; }
  pill("pill-llm", state.llm_ready ? "ok" : "wait", state.llm_ready ? "Model ready" : "Model loading");
  $("fact-model").textContent = `${state.model} (${state.backend === "openai" ? "OpenAI-compatible API" : "local, Ollama"})`;
  $("pill-llm").title = state.llm_ready
    ? "The language model is ready. Simple commands do not need it."
    : `The language model is still loading${state.llm_error ? ` (${state.llm_error})` : ""}. Simple commands already work.`;
  window.mtb.agent = state;
  if (document.activeElement !== $("llm-only")) $("llm-only").checked = !!state.llm_only;
}, { latched: true });
$("llm-only").addEventListener("change", (e) => ros.bool("/agent/llm_only", e.target.checked));

// What the robot is doing right now, shown over the 3D view.
const VERBS = {
  spawn: "Creating", pick: "Picking up", place: "Placing", move_to: "Moving", move_by: "Moving",
  gripper: "Gripper", home: "Going home", remove: "Removing", reset: "Clearing the table",
};
let activityTimer = null;
function showActivity(html, kind = "", hold = 0) {
  const el = $("activity");
  el.className = `show ${kind}`;
  el.innerHTML = html;
  clearTimeout(activityTimer);
  if (hold) activityTimer = setTimeout(() => { el.className = ""; }, hold);
}
const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
ros.subscribe("/skill/status", "std_msgs/String", (msg) => {
  let status;
  try { status = JSON.parse(msg.data); } catch { return; }
  const what = escapeHtml((status.description || status.skill || "").replace(/^\S+\s?/, ""));
  if (status.state === "running") {
    showActivity(`<span class="dot"></span>${VERBS[status.skill] || status.skill} ${what}`);
  } else if (status.state === "failed") {
    showActivity(escapeHtml(status.message || "failed"), "error", 4000);
  } else {
    showActivity(escapeHtml((status.message || "done").replace(/^./, (c) => c.toUpperCase())), "", 1500);
  }
}, { queue: 50 });

// ------------------------------------------------------------------ voice

const speech = new Speech({
  onText: (text) => { rec?.source(text, "voice"); send(text); },
  onState: (state) => {
    $("mic").setAttribute("aria-pressed", state === "listening" ? "true" : "false");
    $("mic").classList.toggle("busy", state === "transcribing");
    $("mic").title = { idle: "Speak a command", listening: "Listening… click to finish", transcribing: "Transcribing…" }[state];
  },
  onError: (message) => addEntry("error", message),
});
if (!speech.browserSupported) {
  $("local-speech").checked = true;
  $("local-speech").disabled = true;
  speech.setMode("local");
}
$("local-speech").addEventListener("change", (e) => speech.setMode(e.target.checked ? "local" : "browser"));
$("mic").addEventListener("click", () => speech.toggle());

// ----------------------------------------------------------- hand control

let lastTeleopSend = 0;
function sendTarget({ position, gripper }) {
  viewer.setHand([position.x, position.y, position.z]);
  const now = performance.now();
  if (now - lastTeleopSend < 60) return;         // about 15 messages a second
  lastTeleopSend = now;
  ros.publish("/teleop/target", "geometry_msgs/Point", position);
  ros.publish("/teleop/gripper", "std_msgs/Float32", { data: gripper });
}
const hand = new HandControl({
  video: $("camera"),
  canvas: $("hand-canvas"),
  onTarget: sendTarget,
  onLost: () => viewer.setHand(null),
  onStatus: (text) => { $("hand-status").textContent = text; },
});
let teleopOn = false;
let keepAlive = null;
function setTeleop(on) {
  teleopOn = on;
  $("hand-toggle").setAttribute("aria-pressed", on ? "true" : "false");
  $("hand-preview").hidden = !on;
  ros.bool("/teleop/enable", on);
  clearInterval(keepAlive);
  // Repeat the switch so the robot gets it even if ROS restarts while the page is open.
  if (on) keepAlive = setInterval(() => ros.bool("/teleop/enable", true), 2000);
  if (!on) viewer.setHand(null);
  rec?.setTeleop(on);
}
$("hand-toggle").addEventListener("click", async () => {
  if (teleopOn) {
    hand.stop();
    setTeleop(false);
    return;
  }
  setTeleop(true);
  try {
    await hand.start();
  } catch (e) {
    setTeleop(false);
    addEntry("error", e && e.name === "NotAllowedError"
      ? "The camera is blocked: allow it in the browser's address bar, then try again."
      : `Hand control could not start: ${e.message || e}`);
  }
});
window.addEventListener("beforeunload", () => { if (teleopOn) ros.bool("/teleop/enable", false); });

Object.assign(window.mtb, {
  hand, send, fakeHand,
  ready: () => ros.connected && robotReady && !!viewer.robot,
  teleop: (on) => { setTeleop(on); if (on) { hand.mapper.reset(); $("hand-status").textContent = "Following your hand. Pinch to grab."; } },
  feedHand: (options) => hand.feed(options ? fakeHand(options) : null),
});

// The object scanner: its button only appears when the scan service runs (./run.sh --scan).
new Scanner({
  send: (text) => { rec?.source(text, "scan"); send(text); },
  onEvent: (state, info) => rec?.scan(state, info),
});

if (params.has("rec")) {
  rec = new Recording({ ros, viewer, params, actions: {
    send, stop: () => send("stop"),
    toggleHand: () => $("hand-toggle").click(), toggleMic: () => $("mic").click(),
  } });
}
