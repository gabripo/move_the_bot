const ROSBRIDGE_URL = `ws://${window.location.hostname}/ws/`;

let bridge;
let viewer;
let perception;

window.addEventListener("load", () => {
  viewer = new RobotViewer("viewer");
  bridge = new RosbridgeClient(ROSBRIDGE_URL);
  bridge.setViewer(viewer);
  perception = new PerceptionModule(bridge);

  // Camera toggle
  document.getElementById("btn-camera").addEventListener("click", () => {
    if (perception.cameraActive) {
      perception.stopCamera();
      document.getElementById("btn-camera").textContent = "Start Camera";
      document.getElementById("btn-camera").classList.remove("active");
    } else {
      perception.startCamera();
      document.getElementById("btn-camera").textContent = "Stop Camera";
      document.getElementById("btn-camera").classList.add("active");
    }
  });

  // Mic toggle
  document.getElementById("btn-mic").addEventListener("click", () => {
    perception.toggleMic();
  });

  // Reset button
  document.getElementById("btn-reset").addEventListener("click", () => {
    bridge.resetEnvironment();
  });

  // Text input
  const textInput = document.getElementById("text-input");
  const textSend = document.getElementById("text-send");

  const sendText = () => {
    const text = textInput.value.trim();
    if (!text) return;
    bridge.publishString("/voice_commands", text);
    bridge.addLogEntry(`Sent: "${text}"`);
    document.getElementById("voice").innerHTML =
      `<span class="stat-label">Voice:</span> <span class="stat-value">"${text}"</span>`;
    textInput.value = "";
  };

  textSend.addEventListener("click", sendText);
  textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendText();
  });

  // Handle window resize
  window.addEventListener("resize", () => {
    const w = document.getElementById("viewer").clientWidth;
    const h = document.getElementById("viewer").clientHeight;
    viewer.camera.aspect = w / h;
    viewer.camera.updateProjectionMatrix();
    viewer.renderer.setSize(w, h);
  });
});
