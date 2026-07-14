# Kinematics Analysis & Solver Background

## 1. Arm Geometry Overview

The `simple_arm` is a 4-DOF serial manipulator with three revolute joints and one prismatic joint. In its zero configuration (all joint angles = 0), the arm extends vertically upward. The chain is:

```
base_link                    [origin: (0, 0, 0)]
  └─ base_joint (θ₁)        Z-axis rotation (yaw)
      └─ shoulder_link
          └─ shoulder_joint (θ₂)  Y-axis rotation (pitch)
              └─ upper_arm_link   [length: 0.25 m]
                  └─ elbow_joint (θ₃)  Y-axis rotation (pitch)
                      └─ forearm_link  [length: 0.25 m]
                          └─ gripper_joint (d₄)  Y-axis translation
                              └─ gripper_link
```

**Link lengths:**
- `L₀ = 0.20 m` — shoulder_link height (from base_joint to shoulder_joint)
- `L₁ = 0.25 m` — upper_arm_link length (shoulder_joint to elbow_joint)
- `L₂ = 0.25 m` — forearm_link length (elbow_joint to gripper_joint)

## 2. Kinematic Modeling

### 2.1 Denavit-Hartenberg Convention

A serial manipulator is conventionally modeled using Denavit-Hartenberg (DH) parameters. Each joint-link pair is assigned four parameters that fully describe the transformation from frame `i-1` to frame `i`:

| Parameter | Symbol | Description |
|-----------|--------|-------------|
| Link length | aᵢ | Distance along xᵢ from zᵢ₋₁ to zᵢ |
| Link twist | αᵢ | Angle about xᵢ from zᵢ₋₁ to zᵢ |
| Joint offset | dᵢ | Distance along zᵢ₋₁ from xᵢ₋₁ to xᵢ |
| Joint angle | θᵢ | Angle about zᵢ₋₁ from xᵢ₋₁ to xᵢ |

The homogeneous transformation from frame `i-1` to frame `i` is:

```
Tᵢ = Rot(z, θᵢ) · Trans(z, dᵢ) · Trans(x, aᵢ) · Rot(x, αᵢ)
```

Or in matrix form:

```
Tᵢ = [cos(θᵢ)  -sin(θᵢ)cos(αᵢ)   sin(θᵢ)sin(αᵢ)   aᵢcos(θᵢ)]
     [sin(θᵢ)   cos(θᵢ)cos(αᵢ)  -cos(θᵢ)sin(αᵢ)   aᵢsin(θᵢ)]
     [0          sin(αᵢ)          cos(αᵢ)          dᵢ        ]
     [0          0                0                1          ]
```

### 2.2 DH Table for `simple_arm`

For our arm, using the modified DH convention (as commonly applied to serial chains with parallel axes), the parameters are:

| Joint i | θᵢ | dᵢ | aᵢ | αᵢ |
|---------|-----|-----|-----|------|
| 1 (base) | θ₁ | L₀ | 0 | 90° |
| 2 (shoulder) | θ₂ | 0 | L₁ | 0° |
| 3 (elbow) | θ₃ | 0 | L₂ | 0° |
| 4 (gripper) | 0 | d₄ | 0 | 0° |

Where `θ₁, θ₂, θ₃` are the revolute joint variables, `d₄` is the prismatic gripper extension, `L₀ = 0.20 m`, `L₁ = 0.25 m`, `L₂ = 0.25 m`.

**Notable:** Joint axes 2 and 3 (shoulder and elbow) are parallel (both Y-axis rotations). This makes the arm a **planar 2R manipulator** in the pitch plane, mounted on a yawing base — sometimes called a "SCARA-like" or "anthropomorphic" configuration with a redundant vertical axis.

## 3. Forward Kinematics

The forward kinematics problem: given joint angles `(θ₁, θ₂, θ₃, d₄)`, find the position of `gripper_link` in `base_link` coordinates.

### 3.1 Analytic Derivation

Starting from the DH parameters, we can derive a closed-form expression. The total transformation from base to gripper is:

```
T = T₁ · T₂ · T₃ · T₄
```

Let's compute the position vector `(x, y, z)` of the gripper origin.

**Step 1 — Shoulder joint origin (frame 0 → frame 1):**

```
p_shoulder = (0, 0, L₀) = (0, 0, 0.20)
```

**Step 2 — Elbow joint (frame 0 → frame 2):**

The elbow position depends on θ₁ and θ₂:

```
p_elbow_x = L₁ · sin(θ₂) · cos(θ₁)
p_elbow_y = L₁ · sin(θ₂) · sin(θ₁)
p_elbow_z = L₀ + L₁ · cos(θ₂)
```

**Step 3 — Gripper (frame 0 → frame 4):**

The gripper position adds the forearm contribution:

```
r = L₁ · sin(θ₂) + L₂ · sin(θ₂ + θ₃)
x = r · cos(θ₁)
y = r · sin(θ₁)
z = L₀ + L₁ · cos(θ₂) + L₂ · cos(θ₂ + θ₃)
```

The prismatic joint `d₄` translates along the local Y-axis of the forearm (not the Z-axis), which in the base frame becomes a lateral offset that rotates with θ₁. The gripper position with d₄ applied:

```
r = L₁·sin(θ₂) + L₂·sin(θ₂+θ₃) + d₄·sin(θ₂+θ₃)
x = r · cos(θ₁) + d₄·cos(θ₁)·cos(θ₂+θ₃)    [simplified → see URDF origin offset]
y = r · sin(θ₁) + d₄·sin(θ₁)·cos(θ₂+θ₃)
z = L₀ + L₁·cos(θ₂) + L₂·cos(θ₂+θ₃)
```

However, in the URDF the gripper_joint is placed at `origin xyz="0 0 0.25"` relative to `forearm_link` with axis `0 1 0`. This means d₄ moves the gripper along the forearm's Y-axis after the forearm has been positioned. The gripper_link visual origin also sits at `(0,0,0)` in its own frame (no offset from the joint origin). So the full FK is:

1. Follow the chain to the tip of forearm_link (elbow_joint origin + L₂ along Z in forearm frame)
2. Apply d₄ translation along forearm's Y-axis to get gripper_link position

### 3.2 Forward Kinematics in the Web Viewer

The Three.js viewer in `robot_viewer.js` computes FK explicitly (lines 156-161):

```js
const L0 = 0.20, L1 = 0.25, L2 = 0.25;
const r = L1 * Math.sin(th2) + L2 * Math.sin(th2 + th3);
const zIK = L0 + L1 * Math.cos(th2) + L2 * Math.cos(th2 + th3);
const xIK = r * Math.cos(th1);
const yIK = r * Math.sin(th1);
```

This computes the gripper position in the **IK frame** (ROS `base_link` coordinates: x=forward, y=left, z=up). The result is then transformed to Three.js frame via `ik_to_threejs(xIK, yIK, zIK)` → `(y, z, x)` for display.

The viewer uses a **scene-graph hierarchy** of `THREE.Group` objects to render the arm:

1. `shoulderGroup` — positioned at `(0, 0.05, 0)` in Three.js frame (equivalent to `(0, 0, 0.05)` in IK frame). Rotated by `θ₁` about Y (Three.js) which corresponds to Z (IK frame).
2. `upperArmGroup` — child of `shoulderGroup`, positioned at `(0, 0.15, 0)` → `(0, 0.20, 0)` cumulative from base. Rotated by `θ₂` about X (Three.js) which corresponds to Y (IK frame).
3. `forearmGroup` — child of `upperArmGroup`, positioned at `(0, 0.25, 0)`. Rotated by `θ₃` about X.

The three.js scene graph hierarchy inherently handles the FK composition through matrix multiplication of nested group transforms, avoiding manual trigonometric computation for link rendering.

### 3.3 Forward Kinematics in RViz2 Markers

The `joint_state_to_markers.py` node (lines 181-256) computes FK using explicit rotation matrices:

```python
R_z1 = rotation_z(theta1)   # base_joint
R_y2 = rotation_y(theta2)   # shoulder_joint
R_y3 = rotation_y(theta3)   # elbow_joint
r23 = rotation_y(theta2 + theta3)  # combined shoulder+elbow
```

Joint positions are computed sequentially:

| Position | Computation | ROS Frame |
|----------|-------------|-----------|
| Shoulder | `(0, 0, 0.025)` | base_link |
| Upper arm base | `(0, 0, 0.20)` | base_link |
| Elbow | `p_upper + R_z1 · R_y2 · (0, 0, 0.25)` | base_link |
| Gripper | `p_elbow + R_z1 · r23 · (0, 0, 0.25)` | base_link |

The gripper finger pads are then positioned perpendicular to the forearm direction:

```python
finger_dir = R_z1 · r23 · (0, 1, 0)      # forearm Y-axis in base frame
spread = 0.03 - grip * 0.4               # finger opening
left_finger = p_gripper + spread · finger_dir
right_finger = p_gripper - spread · finger_dir
```

This is a **geometric approach** (not DH-based) that directly mirrors the URDF joint origin chain. The rotation matrices are applied in sequence matching the URDF frame hierarchy.

## 4. Workspace Analysis

The workspace is the set of all reachable gripper positions given joint limits.

### 4.1 Joint Limits

| Joint | Type | Min | Max | Range |
|-------|------|-----|-----|-------|
| `base_joint` (θ₁) | Revolute | -π | +π | 360° (full rotation) |
| `shoulder_joint` (θ₂) | Revolute | -2.0 rad | +2.0 rad | 229° |
| `elbow_joint` (θ₃) | Revolute | -2.5 rad | +2.5 rad | 286° |
| `gripper_joint` (d₄) | Prismatic | 0.0 m | 0.05 m | 0.05 m |

Note: The elbow limit was increased from ±2.0 rad to ±2.5 rad because the target position `(0.25, 0, 0.25)` in the base_link frame requires `θ₃ ≈ 2.071 rad` (118.7°), which exceeded the original ±2.0 rad limit by 4°.

### 4.2 Reachable Region

With θ₁ unconstrained (full rotation), the workspace is a **solid of revolution** about the Z-axis. The cross-section in any vertical plane through the Z-axis is determined by the (θ₂, θ₃) reach:

**Radial reach (r) at a given z-height:**

```
r(θ₂, θ₃) = L₁·sin(θ₂) + L₂·sin(θ₂+θ₃)
z(θ₂, θ₃) = L₀ + L₁·cos(θ₂) + L₂·cos(θ₂+θ₃)
```

With `θ₂ ∈ [-2.0, 2.0]` and `θ₃ ∈ [-2.5, 2.5]`:

| Extremum | θ₂ | θ₃ | r | z |
|----------|----|----|----|----|
| Maximum reach (positive) | ~1.0 rad | ~1.0 rad | ~0.48 m | ~0.43 m |
| Maximum reach (horizontal) | ~1.57 rad | ~-0.5 rad | ~0.45 m | ~0.20 m |
| Home (zero) | 0 | 0 | 0 | 0.70 m |

The arm can reach any point within a **toroidal volume** of radius ~0.48 m, centered on the base Z-axis, with a hollow interior near the base (the arm cannot reach points close to the Z-axis when fully extended forward). The hollow region is small because of the full-yaw capability - the arm can reach any point inside the cylindrical envelope `r < 0.48, z ∈ [z_min, z_max]`.

With the prismatic gripper joint adding +0.05 m along the forearm's local Y-axis, the reachable radius can increase by up to 0.05 m when the forearm is horizontal (θ₂ + θ₃ ≈ π/2), and the z-range gets a small lateral extension.

## 5. Coordinate Frames

The project uses two coordinate frames that must be carefully distinguished:

### 5.1 Three.js Frame (Web Viewer)

```
x = right     (screen right)
y = up        (screen up)
z = toward viewer  (out of screen)
```

### 5.2 ROS base_link Frame (IK Solver, RViz2)

```
x = forward   (away from the base, into the scene)
y = left      (to the robot's left)
z = up        (vertical)
```

### 5.3 Conversion Functions (`coord.js`)

The transformation from Three.js to ROS frame is a cyclic permutation:

```js
threejs_to_ik(x_js, y_js, z_js) → (z_js, x_js, y_js)   // [x_ik, y_ik, z_ik]
ik_to_threejs(x_ik, y_ik, z_ik) → (y_ik, z_ik, x_ik)   // [x_js, y_js, z_js]
```

In matrix form, the `threejs_to_ik` conversion is:

```
[x_ik]   [0  0  1] [x_js]
[y_ik] = [1  0  0] [y_js]
[z_ik]   [0  1  0] [z_js]
```

This is a pure permutation matrix (determinant = +1), so it is a proper rotation — it preserves handedness and distances. No scaling or reflection occurs.

**Why this is needed:** The web UI receives user input in Three.js coordinates (natural for 3D rendering), but the IK solver operates in the ROS `base_link` frame. The rule parser stores object positions in Three.js frame, and the conversion happens before publishing to `/target_goal`. The agent-core node uses its own `_to_ik_frame()` which also applies this same permutation.

## 6. Inverse Kinematics (KDL)

### 6.1 The IK Problem

Given a desired gripper position `(x_d, y_d, z_d)` in the base_link frame, find joint angles `(θ₁, θ₂, θ₃, d₄)` that satisfy:

```
r · cos(θ₁) = x_d
r · sin(θ₁) = y_d
L₀ + L₁·cos(θ₂) + L₂·cos(θ₂+θ₃) = z_d
```

Where `r = L₁·sin(θ₂) + L₂·sin(θ₂+θ₃)`.

This is an **underdetermined system**: 3 equations in 4 unknowns (θ₁ has a closed-form solution given r, but the planar 2R subsystem `(θ₂, θ₃)` has one redundant DOF for 2D positioning).

### 6.2 KDL's ChainIkSolverPos_LMA

KDL (Kinematics and Dynamics Library) provides `ChainIkSolverPos_LMA` — a Levenberg-Marquardt algorithm (LMA) solver for inverse kinematics.

**Levenberg-Marquardt Algorithm:**

LMA interpolates between gradient descent (far from optimum) and Gauss-Newton (near optimum). The update rule is:

```
θ_{k+1} = θ_k - (J^T J + λI)^{-1} J^T e(θ_k)
```

Where:
- `J` = the Jacobian matrix: `J_{ij} = ∂e_i/∂θ_j` (how each error component changes with each joint)
- `e(θ) = f(θ) - p_d` = the residual vector (difference between current FK position and desired position)
- `λ` = the damping factor, adjusted dynamically:
  - If error decreases → reduce λ (move toward Gauss-Newton, faster convergence)
  - If error increases → increase λ (move toward gradient descent, more stable)

**Why LMA works for this arm:**
- LMA does not require a closed-form IK solution — it iteratively minimizes position error
- It naturally handles the redundant DOF: the damping term `λI` regularizes the underdetermined system, selecting the solution closest (in the least-squares sense) to the initial guess
- The initial guess is the current joint configuration, so solutions are locally smooth

**Limitations:**
- LMA finds a **local** solution — it may not find a reachable solution if the initial guess is far from a valid configuration
- It does not guarantee avoiding joint limits (though KDL respects them through projection)
- It has no global awareness of the workspace — it will fail if the target is unreachable

### 6.3 The KDLKinematicsPlugin

MoveIt wraps KDL's IK solver in `kdl_kinematics_plugin/KDLKinematicsPlugin`. Our configuration in `kinematics.yaml`:

```yaml
arm_with_gripper:
  kinematics_solver: kdl_kinematics_plugin/KDLKinematicsPlugin
  kinematics_solver_timeout: 0.1
  kinematics_solver_attempts: 3
  position_only_ik: true
```

Key parameters:
- **`kinematics_solver_timeout: 0.1`** — maximum time per IK attempt (100 ms). Increased from the default 5 ms because KDL's LMA may need more iterations for a 4-DOF chain.
- **`kinematics_solver_attempts: 3`** — retry with random restarts if the first attempt fails (helps escape local minima).
- **`position_only_ik: true`** — critical for this arm (see §6.4).

### 6.4 Position-Only IK

A full 6D pose IK would attempt to match both position `(x, y, z)` and orientation `(roll, pitch, yaw)` of the gripper — 6 constraints. With only 4 joints, this is impossible without violating the constraints. The solver would fail because KDL's LMA cannot zero 6 residuals with only 4 DOF.

With `position_only_ik: true`, the solver:
1. Computes only the translational Jacobian `(3 × 4)` instead of the full spatial Jacobian `(6 × 4)`
2. Minimizes only the 3D position error `||p(θ) - p_d||`
3. The 4th DOF (redundant) is resolved by the LMA regularization — it picks the configuration closest to the initial seed

**Why 4 DOF for 3D positioning works:**

The system has 1 redundant DOF, meaning there is a **1D family of solutions** (a curve in joint space) for any reachable target. The LMA regularization `(J^T J + λI)` ensures a unique solution by penalizing large joint displacements from the initial guess. The choice among the infinite solutions depends on the starting configuration.

**Geometric interpretation:** For a fixed `(x, y)` in the horizontal plane, θ₁ is determined up to a sign by `tan(θ₁) = y/x`. The planar 2R chain `(θ₂, θ₃)` then has a 1D redundancy for reaching the required `(r, z)`. The IK solver picks one specific `(θ₂, θ₃)` pair along the solution curve, typically the one closest to the current configuration.

### 6.5 IK in the Planning Pipeline

The `mock_motion_planning_node` uses IK as the **first stage** of a two-stage pipeline:

```
Stage 1: IK             Stage 2: Motion Planning
Position goal            Joint-space goal
    │                         │
    ▼                         ▼
GetPositionIK           GetMotionPlan (OMPL)
    │                         │
    ▼                         ▼
Joint angles            Smooth trajectory
```

This two-stage approach solves a fundamental problem with OMPL workspace goal planning for underactuated arms (see §7.4).

## 7. Motion Planning (OMPL)

### 7.1 Configuration Space (C-space)

The configuration space C of the arm is the set of all possible joint configurations. For `simple_arm`:

```
C = [−π, π] × [−2.0, 2.0] × [−2.5, 2.5] × [0, 0.05]
  = S¹ × [−2.0, 2.0] × [−2.5, 2.5] × [0, 0.05]
```

C is a 4-dimensional space (a torus for the base revolute joint × 3 intervals for the other joints). Each point `q ∈ C` maps to a unique gripper position through forward kinematics.

### 7.2 Sampling-Based Motion Planning

The OMPL (Open Motion Planning Library) provides sampling-based planners that search C-space by:
1. **Sampling** random configurations `q_sample ∈ C`
2. **Checking** if the configuration is collision-free (via the planning scene)
3. **Connecting** valid configurations to form a graph (roadmap) or tree
4. **Extracting** a path from start to goal

These methods are **probabilistically complete**: if a path exists, the probability of finding it approaches 1 as the number of samples approaches infinity. However, they provide no optimality guarantees (unless using asymptotically optimal planners like RRT* or PRM*).

### 7.3 RRTConnect (Bidirectional RRT)

RRTConnect is the default planner for our arm. It grows two Rapidly-exploring Random Trees simultaneously:

```
Tree 1 (from start)          Tree 2 (from goal)
     q_start                      q_goal
       │                            │
   sample random q_rand         sample random q_rand
       │                            │
   extend toward q_rand         extend toward q_rand
       │                            │
   repeat (50%) ...            repeat (50%) ...
       │                            │
       └─────────── CONNECT ─────────┘
```

The key algorithmic steps:

1. **Sample:** Draw a random configuration `q_rand ∈ C` uniformly
2. **Nearest:** Find the nearest node `q_near` in the current tree
3. **Steer:** Move from `q_near` toward `q_rand` by a step size `δ` (or to `q_rand` if closer)
4. **Extend:** Add `q_new = q_near + δ·(q_rand - q_near)/||q_rand - q_near||` if the path `q_near → q_new` is collision-free
5. **Attempt connection:** On alternating iterations, try to connect the two trees directly (not just extend)

**Bidirectional growth** significantly speeds up planning because:
- Each tree explores from its own side, halving the distance to cover
- The trees naturally meet in the middle, avoiding full exploration of the entire C-space
- The connect heuristic (step 5) greedily extends the second tree toward the first tree's newest node

### 7.4 Joint-Space Goals vs Workspace Goals

This is the most important design decision in the project:

**Workspace goals** (position constraints directly on the gripper):
- Problem: The arm has 4 DOF but only 3 position constraints. The goal region in workspace is a 3D ball, but in C-space it maps to a **1D manifold** (a curve). 
- OMPL samples in C-space and must hit this zero-measure set by chance — **rejection sampling cannot find it in reasonable time**.
- OMPL can use `GoalRegion` with validity checks, but each sample must project onto the constraint manifold, which requires solving the IK problem within the planner loop.

**Joint-space goals** (our approach):
- The goal is a box `[θ₁ ± ε] × [θ₂ ± ε] × [θ₃ ± ε] × [d₄ ± ε]` in C-space.
- This has **non-zero measure** in C-space → rejection sampling works.
- OMPL only needs to find a collision-free path from the current configuration to the goal region.
- The goal region is large enough (tolerance ±0.01 rad) that it is easily sampled even by random exploration.

**The two-stage pipeline solves the constraint problem:**

```
Position goal (3D point in workspace)
    │
    ▼
IK solver (projects workspace → C-space point)
    │
    ▼
Joint-space goal (4D box in C-space, volume > 0)
    │
    ▼
OMPL (finds collision-free path from start → goal box)
```

Without IK, OMPL would need to solve a constrained planning problem (planning on a manifold), which is significantly harder. With IK, the constraint is lifted and OMPL plans in the full C-space volume.

### 7.5 Other Available Planners

In addition to RRTConnect, the OMPL configuration includes several other algorithms:

| Planner | Type | Characteristics |
|---------|------|-----------------|
| **RRTConnect** | Geometric, bidirectional | Fast, good for high-DOF, single-query |
| **RRTstar** | Geometric, asymptotically optimal | Converges to optimal path with more samples |
| **PRM** | Probabilistic Roadmap | Good for multi-query (build once, query many times) |
| **EST** | Expansive Space Trees | Single-query, good for narrow passages |
| **BKPIECE** | KPIECE with boundary heuristic | Uses a grid-based decomposition for focused exploration |

We use `RRTConnect` as the default because it offers the fastest planning times for our single-query, low-DOF scenario. RRTstar would be preferred if path optimality (shorter, smoother trajectories) matters more than planning speed.

## 8. The Role of the SRDF

The Semantic Robot Description Format (SRDF) tells MoveIt how to use the kinematic chain defined in the URDF.

### 8.1 Planning Groups

The `arm_with_gripper` group includes all 4 joints:

```xml
<group name="arm_with_gripper">
    <joint name="base_joint"/>
    <joint name="shoulder_joint"/>
    <joint name="elbow_joint"/>
    <joint name="gripper_joint"/>
</group>
```

The gripper group is a single joint:

```xml
<group name="gripper">
    <joint name="gripper_joint"/>
</group>
```

**Why two groups?** The `arm_with_gripper` group is used for IK and motion planning (the solver sees 4 coupled joints). The `gripper` group allows independent control of the gripper joint for grasp/release without involving IK or motion planning.

### 8.2 End-Effector Declaration

```xml
<end_effector name="gripper_ee" parent_link="forearm_link"
              parent_group="arm_with_gripper" group="gripper"/>
```

This attaches the gripper group as a child end-effector of the arm group. The `parent_link="forearm_link"` tells the visualization where to place interaction markers. In RViz2, this allows dragging the end-effector arrow to set pose goals interactively.

### 8.3 Disabled Collisions

```xml
<disable_default_collisions/>
```

This turns off MoveIt's automatic collision pair generation. All collision checking is instead managed through the planning scene, which is populated programmatically (table object added by the planning node). This avoids spurious self-collision detections from the simple box geometry approximations.

## 9. The Jacobian

The Jacobian matrix maps joint velocities to end-effector velocities:

```
v = J(q) · q̇
```

Where `v ∈ ℝ³` is the gripper translational velocity, `q̇ ∈ ℝ⁴` is the joint velocity vector, and `J ∈ ℝ³ˣ⁴`.

### 9.1 Structure

For our arm, the Jacobian has columns corresponding to each joint:

| Joint | Column (twist) in base frame | Description |
|-------|------------------------------|-------------|
| base (θ₁) | `(0, 0, 1) × (p_gripper − p_base)` | Rotation about Z at base |
| shoulder (θ₂) | `R_z₁ · (0, 1, 0) × (p_gripper − p_shoulder)` | Rotation about Y at shoulder (projected) |
| elbow (θ₃) | `R_z₁ · R_y₂ · (0, 1, 0) × (p_gripper − p_elbow)` | Rotation about Y at elbow (projected) |
| gripper (d₄) | `R_z₁ · R_y₂ · R_y₃ · (0, 1, 0)` | Pure translation along forearm Y-axis |

Each column represents the instantaneous end-effector velocity induced by a unit velocity at that joint.

### 9.2 Singularities

The Jacobian becomes rank-deficient (singular) when:

1. **Shoulder singularity:** When `sin(θ₂) = 0` (arm fully vertical), the shoulder and elbow columns become coplanar with the base column's moment — the arm cannot instantaneously move radially.
2. **Elbow straight:** When `θ₃ = 0` (forearm aligned with upper arm), the elbow contributes the same direction as the shoulder, reducing the usable DOF.
3. **Elbow folded:** When `θ₂ + θ₃ = 0` (arm fully extended upward), the shoulder and elbow act as a single effective joint.

KDL's LMA naturally handles singularities through the damping factor `λ` — near singularities, `J^T J` becomes ill-conditioned, and the increased `λ` keeps the update stable by preferring smaller joint motions.

## 10. Solver Comparison

| Aspect | KDL (IK) | OMPL (Motion Planning) |
|--------|----------|------------------------|
| **Problem** | Find joint angles for a given end-effector position | Find a collision-free path between two configurations |
| **Input** | Desired gripper position (3D) | Start and goal joint configurations (4D) |
| **Output** | Single joint configuration (4 values) | Trajectory (sequence of joint states with timestamps) |
| **Method** | Levenberg-Marquardt (numerical optimization) | Sampling-based search (RRT, PRM, etc.) |
| **Search space** | Continuous, local (iterates from seed) | Global (samples the entire C-space) |
| **Collision awareness** | No (pure kinematics) | Yes (uses planning scene) |
| **Complexity** | O(n³) per iteration (matrix inversion) | O(k log k) for k samples |
| **Deterministic** | Yes (same seed → same result) | No (random sampling) |

## 11. Summary of Modeling Choices

| Decision | Rationale |
|----------|-----------|
| 4 DOF (3R + 1P) for 3D positioning | One redundant DOF enables IK regularization; 4 joints form a fully constrained C-space for planning |
| `position_only_ik: true` | Necessary because 4 DOF cannot satisfy 6D pose constraints |
| Two-stage pipeline (IK → OMPL) | Converts zero-measure workspace goal to non-zero-measure C-space goal for OMPL sampling |
| Joint-space OMPL goals (with tolerance) | Avoids constrained planning on a 1D manifold which would be required for workspace goals |
| RRTConnect planner | Fast bidirectional search for single-query; well-suited to low-DOF (~4-6) manipulators |
| LMA IK solver | Handles redundancy through damping regularization; stable convergence from local seed |
| Elbow limit increased to ±2.5 rad | Required because target position `(0.25, 0, 0.25)` needs 118.7° elbow angle |
| Separated planning and gripper groups | IK/planning operates on 4-DOF group; grasp/release operates on 1-DOF group independently |
