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
- $L_0 = 0.20\text{ m}$ — shoulder_link height (from base_joint to shoulder_joint)
- $L_1 = 0.25\text{ m}$ — upper_arm_link length (shoulder_joint to elbow_joint)
- $L_2 = 0.25\text{ m}$ — forearm_link length (elbow_joint to gripper_joint)

## 2. Kinematic Modeling

### 2.1 Denavit-Hartenberg Convention

A serial manipulator is conventionally modeled using Denavit-Hartenberg (DH) parameters. Each joint-link pair is assigned four parameters that fully describe the transformation from frame `i-1` to frame `i`:

| Parameter | Symbol | Description |
|-----------|--------|-------------|
| Link length | $a_i$ | Distance along $x_i$ from $z_{i-1}$ to $z_i$ |
| Link twist | $\alpha_i$ | Angle about $x_i$ from $z_{i-1}$ to $z_i$ |
| Joint offset | $d_i$ | Distance along $z_{i-1}$ from $x_{i-1}$ to $x_i$ |
| Joint angle | $\theta_i$ | Angle about $z_{i-1}$ from $x_{i-1}$ to $x_i$ |

The homogeneous transformation from frame $i-1$ to frame $i$ is:

$$T_i = \text{Rot}(z, \theta_i) \cdot \text{Trans}(z, d_i) \cdot \text{Trans}(x, a_i) \cdot \text{Rot}(x, \alpha_i)$$

Or in matrix form:

$$T_i = \begin{bmatrix}
\cos\theta_i & -\sin\theta_i\cos\alpha_i & \sin\theta_i\sin\alpha_i & a_i\cos\theta_i \\
\sin\theta_i & \cos\theta_i\cos\alpha_i & -\cos\theta_i\sin\alpha_i & a_i\sin\theta_i \\
0 & \sin\alpha_i & \cos\alpha_i & d_i \\
0 & 0 & 0 & 1
\end{bmatrix}$$

### 2.2 DH Table for `simple_arm`

For our arm, using the modified DH convention (as commonly applied to serial chains with parallel axes), the parameters are:

| Joint $i$ | $\theta_i$ | $d_i$ | $a_i$ | $\alpha_i$ |
|-----------|------------|-------|-------|------------|
| 1 (base) | $\theta_1$ | $L_0$ | $0$ | $90^\circ$ |
| 2 (shoulder) | $\theta_2$ | $0$ | $L_1$ | $0^\circ$ |
| 3 (elbow) | $\theta_3$ | $0$ | $L_2$ | $0^\circ$ |
| 4 (gripper) | $0$ | $d_4$ | $0$ | $0^\circ$ |

Where $\theta_1, \theta_2, \theta_3$ are the revolute joint variables, $d_4$ is the prismatic gripper extension, $L_0 = 0.20\text{ m}$, $L_1 = 0.25\text{ m}$, $L_2 = 0.25\text{ m}$.

**Notable:** Joint axes 2 and 3 (shoulder and elbow) are parallel (both Y-axis rotations). This makes the arm a **planar 2R manipulator** in the pitch plane, mounted on a yawing base — sometimes called a "SCARA-like" or "anthropomorphic" configuration with a redundant vertical axis.

## 3. Forward Kinematics

The forward kinematics problem: given joint angles $(\theta_1, \theta_2, \theta_3, d_4)$, find the position of `gripper_link` in `base_link` coordinates.

### 3.1 Analytic Derivation

Starting from the DH parameters, we can derive a closed-form expression. The total transformation from base to gripper is:

$$T = T_1 \cdot T_2 \cdot T_3 \cdot T_4$$

Let's compute the position vector $(x, y, z)^T$ of the gripper origin.

**Step 1 — Shoulder joint origin (frame 0 → frame 1):**

$$p_\text{shoulder} = (0, 0, L_0) = (0, 0, 0.20)$$

**Step 2 — Elbow joint (frame 0 → frame 2):**

The elbow position depends on $\theta_1$ and $\theta_2$:

$$
\begin{aligned}
p_\text{elbow,x} &= L_1 \sin\theta_2 \cos\theta_1 \\
p_\text{elbow,y} &= L_1 \sin\theta_2 \sin\theta_1 \\
p_\text{elbow,z} &= L_0 + L_1 \cos\theta_2
\end{aligned}
$$

**Step 3 — Gripper (frame 0 → frame 4):**

The gripper position adds the forearm contribution:

$$
\begin{aligned}
r &= L_1 \sin\theta_2 + L_2 \sin(\theta_2 + \theta_3) \\
x &= r \cos\theta_1 \\
y &= r \sin\theta_1 \\
z &= L_0 + L_1 \cos\theta_2 + L_2 \cos(\theta_2 + \theta_3)
\end{aligned}
$$

The prismatic joint $d_4$ translates along the local Y-axis of the forearm (not the Z-axis), which in the base frame becomes a lateral offset that rotates with $\theta_1$. The gripper position with $d_4$ applied:

$$
\begin{aligned}
r &= L_1\sin\theta_2 + L_2\sin(\theta_2+\theta_3) + d_4\sin(\theta_2+\theta_3) \\
x &= r \cos\theta_1 + d_4\cos\theta_1\cos(\theta_2+\theta_3) \\
y &= r \sin\theta_1 + d_4\sin\theta_1\cos(\theta_2+\theta_3) \\
z &= L_0 + L_1\cos\theta_2 + L_2\cos(\theta_2+\theta_3)
\end{aligned}
$$

However, in the URDF the gripper_joint is placed at `origin xyz="0 0 0.25"` relative to `forearm_link` with axis `0 1 0`. This means $d_4$ moves the gripper along the forearm's Y-axis after the forearm has been positioned. The gripper_link visual origin also sits at $(0,0,0)$ in its own frame (no offset from the joint origin). So the full FK is:

1. Follow the chain to the tip of forearm_link (elbow_joint origin + $L_2$ along Z in forearm frame)
2. Apply $d_4$ translation along forearm's Y-axis to get gripper_link position

### 3.2 Forward Kinematics in the Web Viewer

The Three.js viewer in `robot_viewer.js` computes FK explicitly (lines 156-161):

```js
const L0 = 0.20, L1 = 0.25, L2 = 0.25;
const r = L1 * Math.sin(th2) + L2 * Math.sin(th2 + th3);
const zIK = L0 + L1 * Math.cos(th2) + L2 * Math.cos(th2 + th3);
const xIK = r * Math.cos(th1);
const yIK = r * Math.sin(th1);
```

This computes the gripper position in the **IK frame** (ROS `base_link` coordinates: $x$=forward, $y$=left, $z$=up). The result is then transformed to Three.js frame via $\text{ik\_to\_threejs}(x_\text{IK}, y_\text{IK}, z_\text{IK}) \to (y, z, x)$ for display.

The viewer uses a **scene-graph hierarchy** of `THREE.Group` objects to render the arm:

1. `shoulderGroup` — positioned at $(0, 0.05, 0)$ in Three.js frame (equivalent to $(0, 0, 0.05)$ in IK frame). Rotated by $\theta_1$ about Y (Three.js) which corresponds to Z (IK frame).
2. `upperArmGroup` — child of `shoulderGroup`, positioned at $(0, 0.15, 0)$ → $(0, 0.20, 0)$ cumulative from base. Rotated by $\theta_2$ about X (Three.js) which corresponds to Y (IK frame).
3. `forearmGroup` — child of `upperArmGroup`, positioned at $(0, 0.25, 0)$. Rotated by $\theta_3$ about X.

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
| Shoulder | $(0, 0, 0.025)$ | base_link |
| Upper arm base | $(0, 0, 0.20)$ | base_link |
| Elbow | $p_\text{upper} + R_{z1} \cdot R_{y2} \cdot (0, 0, 0.25)$ | base_link |
| Gripper | $p_\text{elbow} + R_{z1} \cdot r_{23} \cdot (0, 0, 0.25)$ | base_link |

The gripper finger pads are then positioned perpendicular to the forearm direction:

$$
\begin{aligned}
d_\text{finger} &= R_{z1} \cdot r_{23} \cdot (0, 1, 0) &&\text{(forearm Y-axis in base frame)} \\
s &= 0.03 - \text{grip} \times 0.4 &&\text{(finger opening)} \\
p_\text{left} &= p_\text{gripper} + s \cdot d_\text{finger} \\
p_\text{right} &= p_\text{gripper} - s \cdot d_\text{finger}
\end{aligned}
$$

This is a **geometric approach** (not DH-based) that directly mirrors the URDF joint origin chain. The rotation matrices are applied in sequence matching the URDF frame hierarchy.

## 4. Workspace Analysis

The workspace is the set of all reachable gripper positions given joint limits.

### 4.1 Joint Limits

| Joint | Type | Min | Max | Range |
|-------|------|-----|-----|-------|
| `base_joint` ($\theta_1$) | Revolute | $-\pi$ | $+\pi$ | $360^\circ$ (full rotation) |
| `shoulder_joint` ($\theta_2$) | Revolute | $-2.0\text{ rad}$ | $+2.0\text{ rad}$ | $229^\circ$ |
| `elbow_joint` ($\theta_3$) | Revolute | $-2.5\text{ rad}$ | $+2.5\text{ rad}$ | $286^\circ$ |
| `gripper_joint` ($d_4$) | Prismatic | $0.0\text{ m}$ | $0.05\text{ m}$ | $0.05\text{ m}$ |

Note: The elbow limit was increased from $\pm 2.0\text{ rad}$ to $\pm 2.5\text{ rad}$ because the target position $(0.25, 0, 0.25)$ in the base_link frame requires $\theta_3 \approx 2.071\text{ rad}$ ($118.7^\circ$), which exceeded the original $\pm 2.0\text{ rad}$ limit by $4^\circ$.

### 4.2 Reachable Region

With $\theta_1$ unconstrained (full rotation), the workspace is a **solid of revolution** about the Z-axis. The cross-section in any vertical plane through the Z-axis is determined by the $(\theta_2, \theta_3)$ reach:

**Radial reach $r$ at a given $z$-height:**

$$
\begin{aligned}
r(\theta_2, \theta_3) &= L_1\sin\theta_2 + L_2\sin(\theta_2+\theta_3) \\
z(\theta_2, \theta_3) &= L_0 + L_1\cos\theta_2 + L_2\cos(\theta_2+\theta_3)
\end{aligned}
$$

With $\theta_2 \in [-2.0, 2.0]$ and $\theta_3 \in [-2.5, 2.5]$:

| Extremum | $\theta_2$ | $\theta_3$ | $r$ | $z$ |
|----------|----|----|----|----|
| Maximum reach (positive) | $\sim 1.0\text{ rad}$ | $\sim 1.0\text{ rad}$ | $\sim 0.48\text{ m}$ | $\sim 0.43\text{ m}$ |
| Maximum reach (horizontal) | $\sim 1.57\text{ rad}$ | $\sim -0.5\text{ rad}$ | $\sim 0.45\text{ m}$ | $\sim 0.20\text{ m}$ |
| Home (zero) | $0$ | $0$ | $0$ | $0.70\text{ m}$ |

The arm can reach any point within a **toroidal volume** of radius $\sim 0.48\text{ m}$, centered on the base Z-axis, with a hollow interior near the base (the arm cannot reach points close to the Z-axis when fully extended forward). The hollow region is small because of the full-yaw capability — the arm can reach any point inside the cylindrical envelope $r < 0.48,\; z \in [z_\text{min}, z_\text{max}]$.

With the prismatic gripper joint adding $+0.05\text{ m}$ along the forearm's local Y-axis, the reachable radius can increase by up to $0.05\text{ m}$ when the forearm is horizontal ($\theta_2 + \theta_3 \approx \pi/2$), and the $z$-range gets a small lateral extension.

## 5. Coordinate Frames

The project uses two coordinate frames that must be carefully distinguished:

### 5.1 Three.js Frame (Web Viewer)

$$
\begin{aligned}
x &= \text{right (screen right)} \\
y &= \text{up (screen up)} \\
z &= \text{toward viewer (out of screen)}
\end{aligned}
$$

### 5.2 ROS base_link Frame (IK Solver, RViz2)

$$
\begin{aligned}
x &= \text{forward (away from base, into scene)} \\
y &= \text{left (to the robot's left)} \\
z &= \text{up (vertical)}
\end{aligned}
$$

### 5.3 Conversion Functions (`coord.js`)

The transformation from Three.js to ROS frame is a cyclic permutation:

$$
\begin{aligned}
\text{threejs\_to\_ik}(x_\text{js}, y_\text{js}, z_\text{js}) &\to (z_\text{js}, x_\text{js}, y_\text{js}) \quad [x_\text{ik}, y_\text{ik}, z_\text{ik}] \\
\text{ik\_to\_threejs}(x_\text{ik}, y_\text{ik}, z_\text{ik}) &\to (y_\text{ik}, z_\text{ik}, x_\text{ik}) \quad [x_\text{js}, y_\text{js}, z_\text{js}]
\end{aligned}
$$

In matrix form, the `threejs_to_ik` conversion is:

$$\begin{bmatrix} x_\text{ik} \\ y_\text{ik} \\ z_\text{ik} \end{bmatrix}
= \begin{bmatrix} 0 & 0 & 1 \\ 1 & 0 & 0 \\ 0 & 1 & 0 \end{bmatrix}
\begin{bmatrix} x_\text{js} \\ y_\text{js} \\ z_\text{js} \end{bmatrix}$$

This is a pure permutation matrix ($\det = +1$), so it is a proper rotation — it preserves handedness and distances. No scaling or reflection occurs.

**Why this is needed:** The web UI receives user input in Three.js coordinates (natural for 3D rendering), but the IK solver operates in the ROS `base_link` frame. The rule parser stores object positions in Three.js frame, and the conversion happens before publishing to `/target_goal`. The agent-core node uses its own `_to_ik_frame()` which also applies this same permutation.

## 6. Inverse Kinematics (KDL)

### 6.1 The IK Problem

Given a desired gripper position $(x_d, y_d, z_d)$ in the base_link frame, find joint angles $(\theta_1, \theta_2, \theta_3, d_4)$ that satisfy:

$$
\begin{aligned}
r \cos\theta_1 &= x_d \\
r \sin\theta_1 &= y_d \\
L_0 + L_1\cos\theta_2 + L_2\cos(\theta_2+\theta_3) &= z_d
\end{aligned}
$$

Where $r = L_1\sin\theta_2 + L_2\sin(\theta_2+\theta_3)$.

This is an **underdetermined system**: 3 equations in 4 unknowns ($\theta_1$ has a closed-form solution given $r$, but the planar 2R subsystem $(\theta_2, \theta_3)$ has one redundant DOF for 2D positioning).

### 6.2 KDL's ChainIkSolverPos_LMA

KDL (Kinematics and Dynamics Library) provides `ChainIkSolverPos_LMA` — a Levenberg-Marquardt algorithm (LMA) solver for inverse kinematics.

**Levenberg-Marquardt Algorithm:**

LMA interpolates between gradient descent (far from optimum) and Gauss-Newton (near optimum). The update rule is:

$$\theta_{k+1} = \theta_k - (J^T J + \lambda I)^{-1} J^T e(\theta_k)$$

Where:
- $J$ = the Jacobian matrix: $J_{ij} = \partial e_i / \partial \theta_j$ (how each error component changes with each joint)
- $e(\theta) = f(\theta) - p_d$ = the residual vector (difference between current FK position and desired position)
- $\lambda$ = the damping factor, adjusted dynamically:
  - If error decreases → reduce $\lambda$ (move toward Gauss-Newton, faster convergence)
  - If error increases → increase $\lambda$ (move toward gradient descent, more stable)

**Why LMA works for this arm:**
- LMA does not require a closed-form IK solution — it iteratively minimizes position error
- It naturally handles the redundant DOF: the damping term $\lambda I$ regularizes the underdetermined system, selecting the solution closest (in the least-squares sense) to the initial guess
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

A full 6D pose IK would attempt to match both position $(x, y, z)$ and orientation $(\text{roll}, \text{pitch}, \text{yaw})$ of the gripper — 6 constraints. With only 4 joints, this is impossible without violating the constraints. The solver would fail because KDL's LMA cannot zero 6 residuals with only 4 DOF.

With `position_only_ik: true`, the solver:
1. Computes only the translational Jacobian $J \in \mathbb{R}^{3 \times 4}$ instead of the full spatial Jacobian $J \in \mathbb{R}^{6 \times 4}$
2. Minimizes only the 3D position error $\|p(\theta) - p_d\|$
3. The 4th DOF (redundant) is resolved by the LMA regularization — it picks the configuration closest to the initial seed

**Why 4 DOF for 3D positioning works:**

The system has 1 redundant DOF, meaning there is a **1D family of solutions** (a curve in joint space) for any reachable target. The LMA regularization $(J^T J + \lambda I)$ ensures a unique solution by penalizing large joint displacements from the initial guess. The choice among the infinite solutions depends on the starting configuration.

**Geometric interpretation:** For a fixed $(x, y)$ in the horizontal plane, $\theta_1$ is determined up to a sign by $\tan\theta_1 = y/x$. The planar 2R chain $(\theta_2, \theta_3)$ then has a 1D redundancy for reaching the required $(r, z)$. The IK solver picks one specific $(\theta_2, \theta_3)$ pair along the solution curve, typically the one closest to the current configuration.

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

The configuration space $\mathcal{C}$ of the arm is the set of all possible joint configurations. For `simple_arm`:

$$\mathcal{C} = [-\pi,\; \pi] \times [-2.0,\; 2.0] \times [-2.5,\; 2.5] \times [0,\; 0.05]
          = \mathbb{S}^1 \times [-2.0,\; 2.0] \times [-2.5,\; 2.5] \times [0,\; 0.05]$$

$\mathcal{C}$ is a 4-dimensional space (a torus for the base revolute joint $\times$ 3 intervals for the other joints). Each point $q \in \mathcal{C}$ maps to a unique gripper position through forward kinematics.

### 7.2 Sampling-Based Motion Planning

The OMPL (Open Motion Planning Library) provides sampling-based planners that search $\mathcal{C}$-space by:
1. **Sampling** random configurations $q_\text{sample} \in \mathcal{C}$
2. **Checking** if the configuration is collision-free (via the planning scene)
3. **Connecting** valid configurations to form a graph (roadmap) or tree
4. **Extracting** a path from start to goal

These methods are **probabilistically complete**: if a path exists, the probability of finding it approaches 1 as the number of samples approaches infinity. However, they provide no optimality guarantees (unless using asymptotically optimal planners like RRT* or PRM*).

### 7.3 RRTConnect (Bidirectional RRT)

RRTConnect is the default planner for our arm. It grows two Rapidly-exploring Random Trees simultaneously:

$$
\begin{array}{c|c}
\text{Tree 1 (from start)} & \text{Tree 2 (from goal)} \\
\hline
q_\text{start} & q_\text{goal} \\
\downarrow & \downarrow \\
\text{sample random } q_\text{rand} & \text{sample random } q_\text{rand} \\
\downarrow & \downarrow \\
\text{extend toward } q_\text{rand} & \text{extend toward } q_\text{rand} \\
\downarrow & \downarrow \\
\text{repeat (50%)} \dots & \text{repeat (50%)} \dots \\
\downarrow & \downarrow \\
\multicolumn{2}{c}{\text{CONNECT}}
\end{array}
$$

The key algorithmic steps:

1. **Sample:** Draw a random configuration $q_\text{rand} \in \mathcal{C}$ uniformly
2. **Nearest:** Find the nearest node $q_\text{near}$ in the current tree
3. **Steer:** Move from $q_\text{near}$ toward $q_\text{rand}$ by a step size $\delta$ (or to $q_\text{rand}$ if closer)
4. **Extend:** Add $q_\text{new} = q_\text{near} + \delta \cdot (q_\text{rand} - q_\text{near}) / \|q_\text{rand} - q_\text{near}\|$ if the path $q_\text{near} \to q_\text{new}$ is collision-free
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
- The goal is a box $[\theta_1 \pm \varepsilon] \times [\theta_2 \pm \varepsilon] \times [\theta_3 \pm \varepsilon] \times [d_4 \pm \varepsilon]$ in $\mathcal{C}$-space.
- This has **non-zero measure** in $\mathcal{C}$-space → rejection sampling works.
- OMPL only needs to find a collision-free path from the current configuration to the goal region.
- The goal region is large enough (tolerance $\pm 0.01\text{ rad}$) that it is easily sampled even by random exploration.

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

$$v = J(q) \cdot \dot{q}$$

Where $v \in \mathbb{R}^3$ is the gripper translational velocity, $\dot{q} \in \mathbb{R}^4$ is the joint velocity vector, and $J \in \mathbb{R}^{3 \times 4}$.

### 9.1 Structure

For our arm, the Jacobian has columns corresponding to each joint:

| Joint | Column (twist) in base frame | Description |
|-------|------------------------------|-------------|
| base ($\theta_1$) | $(0, 0, 1) \times (p_\text{gripper} - p_\text{base})$ | Rotation about Z at base |
| shoulder ($\theta_2$) | $R_{z1} \cdot (0, 1, 0) \times (p_\text{gripper} - p_\text{shoulder})$ | Rotation about Y at shoulder (projected) |
| elbow ($\theta_3$) | $R_{z1} \cdot R_{y2} \cdot (0, 1, 0) \times (p_\text{gripper} - p_\text{elbow})$ | Rotation about Y at elbow (projected) |
| gripper ($d_4$) | $R_{z1} \cdot R_{y2} \cdot R_{y3} \cdot (0, 1, 0)$ | Pure translation along forearm Y-axis |

Each column represents the instantaneous end-effector velocity induced by a unit velocity at that joint.

### 9.2 Singularities

The Jacobian becomes rank-deficient (singular) when:

1. **Shoulder singularity:** When $\sin\theta_2 = 0$ (arm fully vertical), the shoulder and elbow columns become coplanar with the base column's moment — the arm cannot instantaneously move radially.
2. **Elbow straight:** When $\theta_3 = 0$ (forearm aligned with upper arm), the elbow contributes the same direction as the shoulder, reducing the usable DOF.
3. **Elbow folded:** When $\theta_2 + \theta_3 = 0$ (arm fully extended upward), the shoulder and elbow act as a single effective joint.

KDL's LMA naturally handles singularities through the damping factor $\lambda$ — near singularities, $J^T J$ becomes ill-conditioned, and the increased $\lambda$ keeps the update stable by preferring smaller joint motions.

## 10. Solver Comparison

| Aspect | KDL (IK) | OMPL (Motion Planning) |
|--------|----------|------------------------|
| **Problem** | Find joint angles for a given end-effector position | Find a collision-free path between two configurations |
| **Input** | Desired gripper position (3D) | Start and goal joint configurations (4D) |
| **Output** | Single joint configuration (4 values) | Trajectory (sequence of joint states with timestamps) |
| **Method** | Levenberg-Marquardt (numerical optimization) | Sampling-based search (RRT, PRM, etc.) |
| **Search space** | Continuous, local (iterates from seed) | Global (samples entire $\mathcal{C}$-space) |
| **Collision awareness** | No (pure kinematics) | Yes (uses planning scene) |
| **Complexity** | $O(n^3)$ per iteration (matrix inversion) | $O(k \log k)$ for $k$ samples |
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
| Elbow limit increased to $\pm 2.5\text{ rad}$ | Required because target position $(0.25, 0, 0.25)$ needs $118.7^\circ$ elbow angle |
| Separated planning and gripper groups | IK/planning operates on 4-DOF group; grasp/release operates on 1-DOF group independently |
