import { Type } from "typebox";
import { getRosbridgeClient } from "./rosbridge.js";
import { lookupModel } from "./model_lookup.js";

export function registerTools(tool: any) {
  return [
    tool({
      name: "arm_move",
      description: "Move the robotic arm end-effector to a 3D position in meters",
      schema: {
        x: Type.Number({ description: "X position in meters. Range: [-0.5, 0.5]" }),
        y: Type.Number({ description: "Y position in meters. Range: [0.0, 0.5]" }),
        z: Type.Number({ description: "Z position in meters. Range: [0.0, 0.5]" }),
      },
      async execute({ x, y, z }: { x: number; y: number; z: number }) {
        const bridge = getRosbridgeClient();
        bridge.publishPoint("/target_goal", x, y, z);
        return `Moving arm to (${x.toFixed(3)}, ${y.toFixed(3)}, ${z.toFixed(3)})`;
      },
    }),

    tool({
      name: "arm_grasp",
      description: "Close the gripper to grasp an object",
      schema: {},
      async execute() {
        const bridge = getRosbridgeClient();
        bridge.publishString("/grasp_command", "grasp");
        return "Gripper closed";
      },
    }),

    tool({
      name: "arm_release",
      description: "Open the gripper to release an object",
      schema: {},
      async execute() {
        const bridge = getRosbridgeClient();
        bridge.publishString("/grasp_command", "release");
        return "Gripper opened";
      },
    }),

    tool({
      name: "spawn_object",
      description: "Place a 3D object in the simulation at a given position",
      schema: {
        name: Type.String({ description: "Object name (e.g., 'apple', 'mug', 'bottle')" }),
        x: Type.Number({ description: "X position in meters" }),
        y: Type.Number({ description: "Y position in meters" }),
        z: Type.Number({ description: "Z position in meters" }),
      },
      async execute({ name, x, y, z }: { name: string; x: number; y: number; z: number }) {
        const modelPath = await lookupModel(name);
        if (!modelPath) {
          return `Error: No 3D model found for "${name}". Available builtin models: apple, mug, bottle, cube, sphere, table, cylinder, can.`;
        }
        const bridge = getRosbridgeClient();
        bridge.publishString(
          "/object_spawn",
          JSON.stringify({ name, path: modelPath, x, y, z })
        );
        return `Placed ${name} at (${x.toFixed(3)}, ${y.toFixed(3)}, ${z.toFixed(3)})`;
      },
    }),
  ];
}
