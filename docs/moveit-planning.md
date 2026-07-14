# MoveIt 2 Motion Planning

This document describes the MoveIt 2 integration for the `simple_arm` robot, including the `mock_motion_planning_node` and the RViz2 MotionPlanning plugin setup.

## Architecture

### Data Flow

```
/target_goal (PoseStamped)
       │
       ▼
┌──────────────────────────────────────┐
│ mock_motion_planning_node            │  →  /joint_states (JointState)
│  (rclpy.action.ActionClient)         │
│  sends MotionPlanRequest to          │
│  /move_action                        │
└──────────┬───────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│ move_group (moveit_ros_move_group)   │
│  loads config from:                  │
│   • robot_description (URDF)         │
│   • robot_description_semantic (SRDF)│
│   • ompl_planning.yaml               │
│   • kinematics.yaml                  │
│   • joint_limits.yaml                │
└──────────────────────────────────────┘
```

The `mock_motion_planning_node` subscribes to `/target_goal` (PoseStamped), calls `/compute_ik` to find joint angles for `gripper_link` at the target, constructs a joint-space `MotionPlanRequest`, sends it to `/plan_kinematic_path` for OMPL trajectory planning, and replays the planned trajectory by publishing intermediate joint states on `/joint_states`.

### Layer Stack

```
┌──────────────────────────────────────────────┐
│  mock_motion_planning_node                    │
│  (Python rclpy, /compute_ik + /plan_kinematic) │
├─────────────────────────────────────────────┤
│  moveit_configs_utils::MoveItConfigsBuilder │
│  (launch-time YAML loader + dict builder)   │
├─────────────────────────────────────────────┤
│  move_group (moveit_ros_move_group)         │
│  (planning service, OMPL pipelines)         │
├─────────────────────────────────────────────┤
│  OMPL / KDL plugins                         │
│  (motion planners + inverse kinematics)     │
├─────────────────────────────────────────────┤
│  URDF + SRDF                                │
│  (kinematic chain definition)              │
└─────────────────────────────────────────────┘
```

### File Roles

| Layer | Files | Purpose |
|-------|-------|---------|
| **URDF** | `urdf/simple_arm.urdf` | Defines the kinematic chain: links (`base_link`, `forearm_link`, `gripper_link`), joints (`base_joint`, `shoulder_joint`, `elbow_joint` as revolute, `gripper_joint` as prismatic), joint limits, visual geometry |
| **SRDF** | `moveit_config/simple_arm.srdf` | Semantic layer on top of URDF — defines planning groups (`arm`, `gripper`), end-effector (`gripper_ee` attached to `forearm_link`), disabled collision pairs |
| **Planning pipelines** | `moveit_config/ompl_planning.yaml` | Defines OMPL planner configs (RRTConnect, RRTstar, PRM, EST, BKPIECE) and per-group planner selection |
| **Kinematics** | `moveit_config/kinematics.yaml` | IK solver configuration per group — KDL plugin, search resolution, timeout, max attempts |
| **Joint limits** | `moveit_config/joint_limits.yaml` | Position bounds and velocity caps for each joint (used by planners to constrain the search space) |
| **Launcher** | `launch/*.launch.py` | `MoveItConfigsBuilder` loads the files above into a parameter dict, passes it to `move_group` via `Node(parameters=[moveit_config.to_dict()])` |
| **Planner node** | `ros_nodes/mock_motion_planning_node.py` | Receives `/target_goal`, sends `MotionPlanRequest` to `/move_action`, replays trajectory on `/joint_states` |

### Why masses are not needed

MoveIt 2 is a **kinematic-only** motion planner. It solves geometric problems: "what joint angles place the end-effector at this position?" The OMPL planners search the configuration space using joint limits and collision checking — they do **not** simulate forces, torques, or dynamics. Masses and inertias (`<inertial>` elements in URDF) are only required if you plug in a physics simulator (Gazebo, pybullet). Our URDF omits them and planning works without issue.

## Robot Description

### Kinematic Chain

The `simple_arm` is a 4-DOF serial manipulator (3 revolute + 1 prismatic):

```
base_link
    └─ base_joint (revolute, Z-axis, ±3.14 rad)
        └─ shoulder_link
            └─ shoulder_joint (revolute, Y-axis, ±2.0 rad)
                └─ upper_arm_link
                    └─ elbow_joint (revolute, Y-axis, ±2.0 rad)
                        └─ forearm_link
                            └─ gripper_joint (prismatic, Y-axis, 0–0.05 m)
                                └─ gripper_link
```

Joints `base_joint` (yaw), `shoulder_joint` (pitch), and `elbow_joint` (pitch) form a 3-DOF revolute chain. The prismatic `gripper_joint` translates the gripper along the forearm's Y-axis.

### URDF (`urdf/simple_arm.urdf`)

Defines the physical structure: 5 links, 4 joints, no inertial elements (kinematic-only).

**Links** — each has a `<visual>` element with a box geometry and a material color (no collision geometry needed for planning scene-based collision checking):

| Link | Box (m) | Color |
|------|---------|-------|
| `base_link` | 0.15×0.15×0.05 | gray |
| `shoulder_link` | 0.06×0.06×0.20 | blue |
| `upper_arm_link` | 0.05×0.05×0.25 | red |
| `forearm_link` | 0.04×0.04×0.25 | green |
| `gripper_link` | 0.08×0.03×0.03 | yellow |

**Joints** — each `<joint>` specifies the parent/child link pair, the `origin` (position of the child link origin relative to parent), the `axis` of rotation/translation, and the `limit` (bounds + effort/velocity):

| Joint | Type | Parent → Child | Axis | Position limits |
|-------|------|----------------|------|-----------------|
| `base_joint` | revolute | base_link → shoulder_link | Z (0 0 1) | ±3.14 rad |
| `shoulder_joint` | revolute | shoulder_link → upper_arm_link | Y (0 1 0) | ±2.0 rad |
| `elbow_joint` | revolute | upper_arm_link → forearm_link | Y (0 1 0) | ±2.0 rad |
| `gripper_joint` | prismatic | forearm_link → gripper_link | Y (0 1 0) | 0 to 0.05 m |

**Origin offsets** chain the links together:
- `base_joint` at `(0, 0, 0.025)` — sits on top of `base_link`
- `shoulder_joint` at `(0, 0, 0.175)` — top of `shoulder_link`
- `elbow_joint` at `(0, 0, 0.25)` — top of `upper_arm_link`
- `gripper_joint` at `(0, 0, 0.25)` — end of `forearm_link`

No `<inertial>` elements are present — MoveIt plans kinematically without dynamics.

### SRDF (`moveit_config/simple_arm.srdf`)

Semantic layer that tells MoveIt how to group joints for planning. Two planning groups are defined:

```xml
<group name="arm_with_gripper">
    <joint name="base_joint"/>
    <joint name="shoulder_joint"/>
    <joint name="elbow_joint"/>
    <joint name="gripper_joint"/>
</group>
```

The `arm_with_gripper` group contains all 4 joints — end link is `gripper_link`. IK is solved for `gripper_link` using `position_only_ik` (3 position constraints with 4 DOF). The joint-space goal is then passed to OMPL for trajectory planning.

```xml
<group name="gripper">
    <joint name="gripper_joint"/>
</group>
```

The `gripper` group is a single prismatic joint for open/close.

An end-effector is declared for the gripper:

```xml
<end_effector name="gripper_ee" parent_link="forearm_link"
              parent_group="arm_with_gripper" group="gripper"/>
```

This tells MoveIt that `gripper_ee` is attached to `forearm_link`, belongs to the `gripper` group, and is a child of the `arm_with_gripper` group — enabling the RViz2 MotionPlanning plugin to show interaction markers at the gripper.

Finally, `<disable_default_collisions/>` turns off automatic collision pair generation (pairs are managed by the planning scene instead).

### How URDF + SRDF work together

1. `robot_state_publisher` loads the URDF and broadcasts frame transforms (`base_link` → `shoulder_link` → ...)
2. `move_group` loads both URDF (kinematic tree + geometry) and SRDF (planning groups + semantics)
3. The SRDF groups tell MoveIt which joints to include in each planning request
4. The node calls `/compute_ik` for `gripper_link` to get target joint angles, then sends a joint-space `MotionPlanRequest` to OMPL
5. OMPL plans a trajectory from the current joint state to the target joint state (non-zero volume goal in C-space)

## Prerequisites

The `ros-humble-moveit` metapackage is installed inside the ROS 2 container (both amd64 and arm64 Dockerfiles). No additional setup is required.

## Launching

### Full stack (move_group + planning node + RViz2)

```bash
# Inside the running ros2 container:
ros2 launch mock_hmi_core moveit_rviz.launch.py
```

This launches:
1. `robot_state_publisher` — publishes transforms from the URDF
2. `move_group` — the MoveIt 2 planning service
3. `mock_motion_planning` — the planning node (subscribes to `/target_goal`)
4. `rviz2` — with the MoveIt MotionPlanning plugin

### Standalone move_group (no RViz2)

```bash
ros2 launch mock_hmi_core move_group.launch.py
```

## Nodes

### `mock_motion_planning_node`

**Subscribes to:**
- `/target_goal` (geometry_msgs/PoseStamped) — target end-effector pose

**Publishes to:**
- `/joint_states` (sensor_msgs/JointState) — current joint positions (20 Hz)

**Behavior:**
1. Receives a PoseStamped goal on `/target_goal`
2. Calls `/compute_ik` service with group `arm_with_gripper` to compute joint angles for `gripper_link` at the target position
3. Constructs a joint-space `MotionPlanRequest` with `JointConstraint` on each of the 4 joints (tolerance ±0.01 rad)
4. Sends to `/plan_kinematic_path` service; OMPL plans from current state to the joint-space goal
5. On success, replays the trajectory by publishing intermediate joint states at 20 Hz, respecting `time_from_start`
6. Adds a table collision object to the planning scene on startup for obstacle avoidance

**Configured planning group:** `arm_with_gripper` (4 joints: base_joint, shoulder_joint, elbow_joint, gripper_joint). IK is solved for `gripper_link` (position-only), then OMPL plans the trajectory to the joint-space goal.

**Planning defaults:**
| Parameter | Value |
|-----------|-------|
| Planner | RRTConnect |
| Planning time | 10 s |
| Planning attempts | 10 |
| Pipeline | ompl |

## RViz2 MotionPlanning Plugin

The `moveit.rviz` config includes the `moveit_rviz_plugin/MotionPlanning` display configured with:

- **Planning Scene Topic:** `/planning_scene`
- **Planning Group:** `arm_with_gripper` (4 joints: 3 revolute + 1 prismatic)
- **Planner:** `RRTConnect`
- **Trajectory Topic:** `/move_group/display_planned_path`

Use the **MotionPlanning** panel in RViz2 to:
- Visualize the robot model
- Set interactive pose goals (drag the end-effector arrow)
- View the computed planned path
- See collision objects (table) in the planning scene

## Configuration Files

| File | Purpose |
|------|---------|
| `urdf/simple_arm.urdf` | Kinematic chain — links, joints, visual geometry |
| `urdf/simple_arm.srdf` | Semantic robot description — planning groups, end-effector, disabled collisions |
| `moveit_config/ompl_planning.yaml` | OMPL planner definitions (RRTConnect, RRTstar, PRM, EST, BKPIECE) and per-group assignments |
| `moveit_config/kinematics.yaml` | KDL IK solver configuration per group |
| `moveit_config/joint_limits.yaml` | Position and velocity limits for all joints |

## Notes

- All config files are loaded by `MoveItConfigsBuilder` at launch time via `to_moveit_configs().to_dict()` and passed as a single parameter dict to the `move_group` Node.
- A `config → moveit_config` symlink is created at build time in the package share directory so `MoveItConfigsBuilder`'s default `config/` lookup resolves correctly.
- The `moveit_rviz.launch.py` includes `move_group.launch.py`, so both `robot_state_publisher` and `move_group` are started automatically. Do not also launch `deploy.launch.py` or `visualize.launch.py` alongside it (duplicate RSP instances).
- Masses and inertias are **not required** — MoveIt is kinematic-only. It solves geometric planning problems without physics simulation.

## Development Workflow

For faster iteration without full image rebuilds, the Docker Compose file includes commented-out bind mounts for the source directories. This is intended for **development environments only** — production deployments should always build the image.

### Setup

In `docker/docker-compose.yml`, uncomment the four `volumes` entries under the `ros2` service:

```yaml
volumes:
  - model_cache:/models/cache
  - ../ros_nodes:/ros_ws/src/mock_hmi_core/ros_nodes
  - ../launch:/ros_ws/src/mock_hmi_core/launch
  - ../urdf:/ros_ws/src/mock_hmi_core/urdf
  - ../moveit_config:/ros_ws/src/mock_hmi_core/moveit_config
```

Then start the stack without rebuilding:

```bash
docker compose -f docker/docker-compose.yml --profile ollama-agent up -d
```

### Iteration Loop

1. **Edit a file** on your host (e.g., `ros_nodes/mock_motion_planning_node.py`)
2. **Rebuild the package** (needed for launch/config/URDF changes; optional for Python-only changes since `--symlink-install` follows symlinks into the mounted source):

   ```bash
   docker compose exec ros2 bash -c "source install/setup.bash && colcon build --packages-select mock_hmi_core --symlink-install"
   ```

3. **Restart the container** to pick up the updated entry points:

   ```bash
   docker compose restart ros2
   ```

### What requires a full rebuild

| Change | Dev mount workflow | Full rebuild required? |
|--------|-------------------|----------------------|
| Python node logic | Mount + `colcon build` + restart | No |
| Launch files | Mount + `colcon build` + restart | No |
| URDF/SRDF | Mount + `colcon build` + restart | No |
| MoveIt config YAMLs | Mount + `colcon build` + restart  | No |
| Dockerfile (new apt packages) | — | Yes |
| `setup.py` (new entry points) | — | Yes |
| `package.xml` (new deps) | — | Yes |
