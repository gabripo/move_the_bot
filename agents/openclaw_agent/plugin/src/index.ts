import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";
import { registerTools } from "./tools.js";

export default defineToolPlugin({
  id: "hmi-arm-control",
  name: "HMI Arm Control",
  description: "Tools to control a simulated 3-DOF robotic arm via ROS 2",
  tools: registerTools,
});
