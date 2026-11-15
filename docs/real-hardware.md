# From the simulated arm to Isaac Sim and to a real SO-101

Everything above ros2_control (the agent, the skills, MoveIt, the web app) is the same in all
three cases. Only the **hardware plugin** in `robot/so101.urdf.xacro` changes:

| `hardware:=` | Plugin | Joint commands go to |
|---|---|---|
| `mock` (default) | `mock_components/GenericSystem` | an ideal arm inside ros2_control |
| `isaac` | `joint_state_topic_hardware_interface/JointStateTopicSystem` | Isaac Sim, over two ROS topics |
| `real` | `feetech_ros2_driver/FeetechHardwareInterface` | the SO-101's servos, over USB |

What has been verified:

- `mock`: tested end to end on every change.
- `isaac`: the interface is tested on every change with a small node that plays Isaac Sim's part
  (`joint_echo`). It has **not** been run against Isaac Sim itself yet.
- `real`: configured from the driver's documentation. It has **not** been run on an arm yet.
  Treat the steps below as a checklist to work through carefully, not as a guarantee.

## Step 1: Isaac Sim

You need a computer that runs Isaac Sim: Linux or Windows with an NVIDIA RTX GPU
([requirements](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html)).
See [hardware-and-gpus.md](hardware-and-gpus.md) for what to do without one.

1. **Import the arm.** In Isaac Sim, use the URDF importer on
   `ros/move_the_bot/robot/so101.urdf` (fixed base, position drives). Save it as USD.
2. **Add a table and objects** if you want physics: in mock mode objects are only drawn and
   attached to the gripper; in Isaac Sim they can be real rigid bodies.
3. **Add the ROS 2 bridge graph.** Create an Action Graph with:
   - *ROS2 Publish Joint State* on topic `/isaac_joint_states`
   - *ROS2 Subscribe Joint State* on topic `/isaac_joint_commands`, wired into an
     *Articulation Controller* that targets the arm
   - *ROS2 Publish Clock* (optional)

   This is the same pattern as the official
   [MoveIt 2 tutorial for Isaac Sim](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/ros2_tutorials/tutorial_ros2_moveit.html)
   and [MoveIt's own guide](https://moveit.picknik.ai/main/doc/how_to_guides/isaac_panda/isaac_panda_tutorial.html).
4. **Use the same ROS domain.** Start Isaac Sim with `ROS_DOMAIN_ID=42` (the value in
   `docker-compose.yml`), press Play.
5. **Start the stack**: `./run.sh --isaac`. On Linux this puts the robot container on the host
   network so it sees Isaac Sim's topics.
6. **Check** before sending commands:

   ```bash
   docker compose exec robot /ros_entrypoint.sh ros2 topic hz /isaac_joint_states
   docker compose exec robot /ros_entrypoint.sh ros2 control list_controllers
   ```

   Both controllers should be `active`. Then try "go home" in the web app: the arm moves in
   Isaac Sim and in the browser at the same time.

Without Isaac Sim you can still exercise this path:

```bash
HARDWARE=isaac docker compose up -d robot web
docker compose exec -d robot /ros_entrypoint.sh ros2 run move_the_bot joint_echo
```

What will need tuning: drive stiffness and damping in Isaac Sim (so the simulated servos track
like real ones), and the grasp, which with physics depends on friction instead of an "attach".

## Step 2: the real SO-101

### What you need

- An assembled SO-101 follower arm (6 Feetech STS3215 servos with IDs 1 to 6, as set by the
  [LeRobot assembly guide](https://huggingface.co/docs/lerobot/so101)), its power supply and USB cable.
- A Linux computer. Docker Desktop on macOS and Windows does not pass USB serial ports to
  containers easily; on those, run ROS natively or in a Linux virtual machine.
- A clear table. Keep the power supply's plug within reach: pulling it is the emergency stop.

### Steps

1. **Find the serial port.** Plug in the arm and run `ls /dev/ttyACM* /dev/ttyUSB*`. Your user
   must be allowed to use it: `sudo usermod -aG dialout $USER`, then log in again.

2. **Calibrate.** The URDF says where each joint's zero is; each assembled arm differs a little.
   Copy the example and fill it in:

   ```bash
   mkdir -p calibration
   cp ros/move_the_bot/config/so101_calibration.example.yaml calibration/so101.yaml
   ```

   For each joint, `homing_offset` makes the servo read 2048 (mid-range) when the joint is at
   0 rad in the URDF, and `range_min` / `range_max` are the limits it must never pass. If you
   already calibrated the arm with LeRobot, its calibration file contains the same three
   numbers per joint and can be copied over. `./run.sh --real` picks up
   `calibration/so101.yaml` automatically.

3. **First start with the arm unpowered.** Leave the servo power supply off, USB connected:

   ```bash
   ./run.sh --real /dev/ttyACM0
   ./run.sh logs
   ```

   Move the arm by hand and watch the browser. The drawn arm must follow, in the same
   direction, and show the zero pose when the real arm is in the zero pose. If a joint moves
   the wrong way or is offset, fix the calibration before going on.

4. **Check the gripper range.** The skills assume the gripper joint is about 0 rad when closed
   and 1.0 rad when open. If yours differs, adjust the limits in the calibration.

5. **Slow everything down.** In `config/joint_limits.yaml` set `default_velocity_scaling_factor`
   and `default_acceleration_scaling_factor` to a small value (for example 0.1) for the first powered runs.

6. **Power on and test in this order**, one hand on the plug:
   1. "go home"
   2. "move up 2 cm", "a bit to the left"
   3. "open the gripper", "close the gripper"
   4. pick a real object placed where a virtual one is (next section)

7. **Raise the speed** once motions are right.

### What does not carry over by itself

| Topic | In simulation | On the real arm |
|---|---|---|
| Objects | created by a sentence; position known exactly | must be **seen**. Without a camera, put a real object where you spawned the virtual one. Next step: a camera and a detector that fill the same world model (`world.py`). |
| Grasp | the object is attached to the gripper | friction and gripper force; the close width may need a margin |
| Accuracy | exact | a few millimetres of backlash; approach heights may need a margin |
| Table height | z = 0 | measure it: the base may sit on a clamp or a plate |
| Hand teleoperation | no collision checking | the same, so the table limit in `skill_server.py` is the only guard: start slowly |
| Stop | "stop" halts the trajectory | also keep the power plug reachable |

### Where to add perception

The skill server keeps objects in `World` (`move_the_bot/world.py`) and publishes them on
`/scene/objects`. A perception node only has to add and update objects there: for example a
depth camera plus a detector such as
[Isaac ROS FoundationPose](https://nvidia-isaac-ros.github.io/repositories_and_packages/isaac_ros_pose_estimation/index.html),
or simply AprilTags on the objects. Nothing above the world model changes.

## Using another arm

1. Replace the URDF and meshes in `robot/` and the joint list in `so101.urdf.xacro`.
2. Regenerate the MoveIt configuration (`config/so101.srdf`, limits, controllers), for example
   with the MoveIt Setup Assistant.
3. Use the hardware plugin of that arm's ros2_control driver in the `real` branch.
4. For a 6- or 7-joint arm, you can replace the custom inverse kinematics with MoveIt's pose
   goals; `kinematics.py` builds its chain from the URDF, so check the joint names in
   `skill_server.py` either way.
