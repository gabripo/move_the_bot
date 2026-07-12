class RosbridgeClient {
  constructor(url) {
    this.ros = new ROSLIB.Ros({ url });
    this.viewer = null;

    this.ros.on("connection", () => {
      console.log("Connected to rosbridge");
      this.initTopics();
    });
    this.ros.on("error", (e) => console.error("rosbridge error:", e));
    this.ros.on("close", () => console.log("rosbridge disconnected"));

    this.subscribeJointStates();
    this.subscribeObjectSpawn();
    this.subscribeAgentLog();
  }

  initTopics() {
    this.topics = {};

    this.topics["/target_goal"] = new ROSLIB.Topic({
      ros: this.ros, name: "/target_goal", messageType: "geometry_msgs/Point",
    });
    this.topics["/target_goal"].advertise();

    this.topics["/grasp_command"] = new ROSLIB.Topic({
      ros: this.ros, name: "/grasp_command", messageType: "std_msgs/String",
    });
    this.topics["/grasp_command"].advertise();

    this.topics["/voice_commands"] = new ROSLIB.Topic({
      ros: this.ros, name: "/voice_commands", messageType: "std_msgs/String",
    });
    this.topics["/voice_commands"].advertise();

    this.topics["/object_spawn"] = new ROSLIB.Topic({
      ros: this.ros, name: "/object_spawn", messageType: "std_msgs/String",
    });

    this.topics["/reset_command"] = new ROSLIB.Topic({
      ros: this.ros, name: "/reset_command", messageType: "std_msgs/String",
    });
    this.topics["/reset_command"].advertise();
  }

  setViewer(viewer) {
    this.viewer = viewer;
  }

  publishPoint(topic, x, y, z) {
    const t = this.topics[topic] || this.topics["/target_goal"];
    if (!t) return;
    t.publish(new ROSLIB.Message({ x, y, z }));
  }

  publishString(topic, data) {
    const t = this.topics[topic];
    if (!t) return;
    t.publish(new ROSLIB.Message({ data }));
  }

  resetEnvironment() {
    try {
      this.publishString("/reset_command", "reset");
      this.publishString("/grasp_command", "release");
      if (this.viewer) this.viewer.resetEnvironment();
      this.addLogEntry("Environment reset");
    } catch (e) {
      console.error("Reset error:", e);
      this.addLogEntry(`Reset error: ${e.message}`);
    }
  }

  // --- Subscribers ---

  subscribeJointStates() {
    const topic = new ROSLIB.Topic({
      ros: this.ros,
      name: "/joint_states",
      messageType: "sensor_msgs/JointState",
    });
    topic.subscribe((msg) => {
      if (this.viewer) this.viewer.updateJoints(msg.position);

      const th1 = msg.position[0] || 0;
      const th2 = msg.position[1] || 0;
      const th3 = msg.position[2] || 0;

      document.getElementById("angle-base").innerHTML =
        `<span class="stat-label">θ₁ base:</span> <span class="stat-value">${(th1 * 180 / Math.PI).toFixed(1)}°</span>`;
      document.getElementById("angle-shoulder").innerHTML =
        `<span class="stat-label">θ₂ shoulder:</span> <span class="stat-value">${(th2 * 180 / Math.PI).toFixed(1)}°</span>`;
      document.getElementById("angle-elbow").innerHTML =
        `<span class="stat-label">θ₃ elbow:</span> <span class="stat-value">${(th3 * 180 / Math.PI).toFixed(1)}°</span>`;

      // Forward kinematics → end-effector position
      const L0 = 0.20, L1 = 0.25, L2 = 0.25;
      const r = L1 * Math.sin(th2) + L2 * Math.sin(th2 + th3);
      const zIK = L0 + L1 * Math.cos(th2) + L2 * Math.cos(th2 + th3);
      const xIK = r * Math.cos(th1);
      const yIK = r * Math.sin(th1);

      document.getElementById("ee-ik").innerHTML =
        `<span class="stat-label">IK frame:</span> <span class="stat-value">(${xIK.toFixed(3)}, ${yIK.toFixed(3)}, ${zIK.toFixed(3)})</span>`;

      const [tx, ty, tz] = ik_to_threejs(xIK, yIK, zIK);
      document.getElementById("ee-threejs").innerHTML =
        `<span class="stat-label">Three.js:</span> <span class="stat-value">(${tx.toFixed(3)}, ${ty.toFixed(3)}, ${tz.toFixed(3)})</span>`;

      const gripperPos = msg.position[3];
      if (gripperPos !== undefined) {
        document.getElementById("grasp-status").textContent =
          gripperPos > 0.02 ? "closed" : "open";
      }
    });
  }

  subscribeObjectSpawn() {
    const topic = new ROSLIB.Topic({
      ros: this.ros,
      name: "/object_spawn",
      messageType: "std_msgs/String",
    });
    topic.subscribe((msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (this.viewer && data.name && data.x !== undefined) {
          this.viewer.spawnObject(data.name, data.path || "", data.x, data.y, data.z);
        }
        if (data.path) {
          this.addLogEntry(`Spawned: ${data.name} at (${data.x}, ${data.y}, ${data.z})`);
        }
      } catch (e) {
        this.addLogEntry(`Object spawn error: ${e.message}`);
      }
    });
  }

  subscribeAgentLog() {
    const topic = new ROSLIB.Topic({
      ros: this.ros,
      name: "/agent_log",
      messageType: "std_msgs/String",
    });
    topic.subscribe((msg) => {
      this.addLogEntry(msg.data);
    });
  }

  addLogEntry(text) {
    const log = document.getElementById("log");
    const entry = document.createElement("div");
    entry.className = "log-entry";
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${text}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
  }
}
