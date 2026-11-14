"""Forward and inverse kinematics for a serial arm, read straight from its URDF.

Pure Python + NumPy (no ROS imports), so it runs in unit tests and in the ROS nodes alike.

The SO-101 has 5 arm joints. Five joints cannot reach an arbitrary position *and* orientation,
so the IK here solves for what a pick-and-place task needs:

  * the position of the tool point (3 constraints), and
  * the pitch of the gripper: how steeply it points down (1 constraint).

The gripper roll is left where it is. `solve()` tries a list of pitches, starting with
"straight down", and returns the first one that is reachable inside the joint limits.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np


def _rpy_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ])


def _transform(xyz, rpy) -> np.ndarray:
    t = np.eye(4)
    t[:3, :3] = _rpy_matrix(*rpy)
    t[:3, 3] = xyz
    return t


def _axis_rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    k = 1.0 - c
    t = np.eye(4)
    t[:3, :3] = [
        [c + x * x * k, x * y * k - z * s, x * z * k + y * s],
        [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
        [z * x * k - y * s, z * y * k + x * s, c + z * z * k],
    ]
    return t


# Gripper pitches tried by default, steepest first: 90 degrees = pointing straight down.
PITCHES = tuple(math.radians(d) for d in (90, 75, 60, 45, 30, 15, 0))


@dataclass
class _Joint:
    name: str
    kind: str            # "revolute", "continuous", "prismatic" or "fixed"
    origin: np.ndarray   # 4x4 parent link -> joint frame
    axis: np.ndarray
    lower: float
    upper: float


@dataclass
class IKResult:
    joints: np.ndarray   # joint angles, in the order of Chain.joint_names
    pitch: float | None  # gripper pitch used (rad below horizontal); None = position only
    error: float         # remaining position error in metres


class Chain:
    """A serial kinematic chain between two links of a URDF."""

    def __init__(self, joints: list[_Joint]):
        self._joints = joints
        self._moving = [j for j in joints if j.kind != "fixed"]
        self.joint_names = [j.name for j in self._moving]
        self.lower = np.array([j.lower for j in self._moving])
        self.upper = np.array([j.upper for j in self._moving])
        # Which way the first joint turns the arm when seen from above (+1 = counter-clockwise).
        self._pan_sign = 1.0
        if len(self._moving) >= 2:
            q = np.zeros(len(self._moving))
            before = self.position(q)[:2] - self._joints[0].origin[:2, 3]
            q[0] = 0.2
            after = self.position(q)[:2] - self._joints[0].origin[:2, 3]
            turn = before[0] * after[1] - before[1] * after[0]
            self._pan_sign = 1.0 if turn >= 0 else -1.0

    # ------------------------------------------------------------------ loading

    @classmethod
    def from_urdf(cls, urdf_xml: str, base_link: str, tip_link: str) -> "Chain":
        root = ET.fromstring(urdf_xml)
        by_child = {}
        for j in root.findall("joint"):
            by_child[j.find("child").get("link")] = j

        joints: list[_Joint] = []
        link = tip_link
        while link != base_link:
            if link not in by_child:
                raise ValueError(f"No chain from '{base_link}' to '{tip_link}' in the URDF")
            j = by_child[link]
            origin = j.find("origin")
            xyz = [float(v) for v in (origin.get("xyz", "0 0 0") if origin is not None else "0 0 0").split()]
            rpy = [float(v) for v in (origin.get("rpy", "0 0 0") if origin is not None else "0 0 0").split()]
            axis_el = j.find("axis")
            axis = np.array([float(v) for v in (axis_el.get("xyz") if axis_el is not None else "1 0 0").split()])
            norm = np.linalg.norm(axis)
            axis = axis / norm if norm > 0 else np.array([1.0, 0.0, 0.0])
            limit = j.find("limit")
            kind = j.get("type")
            lower = float(limit.get("lower", -math.pi)) if limit is not None and kind != "continuous" else -math.pi
            upper = float(limit.get("upper", math.pi)) if limit is not None and kind != "continuous" else math.pi
            joints.append(_Joint(j.get("name"), kind, _transform(xyz, rpy), axis, lower, upper))
            link = j.find("parent").get("link")
        joints.reverse()
        return cls(joints)

    # --------------------------------------------------------------- kinematics

    def _frames(self, q):
        """Tool pose plus, for each moving joint, its axis and origin in the base frame."""
        t = np.eye(4)
        axes, origins, kinds = [], [], []
        i = 0
        for j in self._joints:
            t = t @ j.origin
            if j.kind == "fixed":
                continue
            axes.append(t[:3, :3] @ j.axis)
            origins.append(t[:3, 3].copy())
            kinds.append(j.kind)
            if j.kind == "prismatic":
                move = np.eye(4)
                move[:3, 3] = j.axis * q[i]
                t = t @ move
            else:
                t = t @ _axis_rotation(j.axis, q[i])
            i += 1
        return t, axes, origins, kinds

    def fk(self, q) -> np.ndarray:
        """4x4 pose of the tip link in the base frame."""
        return self._frames(np.asarray(q, dtype=float))[0]

    def position(self, q) -> np.ndarray:
        return self.fk(q)[:3, 3]

    def jacobian(self, q) -> np.ndarray:
        """6xN geometric Jacobian (linear rows first, then angular), in the base frame."""
        return self._pose_and_jacobian(q)[1]

    def _pose_and_jacobian(self, q):
        t, axes, origins, kinds = self._frames(np.asarray(q, dtype=float))
        tip = t[:3, 3]
        jac = np.zeros((6, len(axes)))
        for i, (axis, origin, kind) in enumerate(zip(axes, origins, kinds)):
            if kind == "prismatic":
                jac[:3, i] = axis
            else:
                jac[:3, i] = np.cross(axis, tip - origin)
                jac[3:, i] = axis
        return t, jac

    def clamp(self, q) -> np.ndarray:
        return np.minimum(np.maximum(np.asarray(q, dtype=float), self.lower), self.upper)

    # ------------------------------------------------------- inverse kinematics

    def approach_direction(self, target, pitch: float) -> np.ndarray:
        """Unit vector the gripper should point along, for a pitch below horizontal.

        The arm is a rotating base plus links that move in one vertical plane, so the gripper can
        only point within the plane through the base axis and the target.
        """
        base_xy = self._joints[0].origin[:2, 3]
        heading = np.asarray(target[:2], dtype=float) - base_xy
        norm = np.linalg.norm(heading)
        heading = heading / norm if norm > 1e-6 else np.array([1.0, 0.0])
        return np.array([math.cos(pitch) * heading[0], math.cos(pitch) * heading[1], -math.sin(pitch)])

    def _iterate(self, target, direction, seed, iterations, tolerance, tool_axis):
        q = self.clamp(seed)
        damping = 0.02
        best, stalled = float("inf"), 0
        for _ in range(iterations):
            t, jac = self._pose_and_jacobian(q)
            e_pos = target - t[:3, 3]
            if direction is None:
                error, j_task = e_pos, jac[:3]
            else:
                a = t[:3, :3] @ tool_axis
                # Rotation that turns the tool axis onto the wanted direction. Spin about the
                # axis itself does not matter, so that component is projected away.
                e_rot = np.cross(a, direction)
                if np.dot(a, direction) < 0:      # pointing the opposite way: push harder
                    n = np.linalg.norm(e_rot)
                    e_rot = e_rot / n if n > 1e-9 else np.cross(a, [0.0, 0.0, 1.0])
                project = np.eye(3) - np.outer(a, a)
                error = np.concatenate([e_pos, 0.3 * (project @ e_rot)])
                j_task = np.vstack([jac[:3], 0.3 * (project @ jac[3:])])
            if np.linalg.norm(e_pos) < tolerance and (direction is None or np.linalg.norm(error[3:]) < 0.01):
                return q, float(np.linalg.norm(e_pos))
            # Give up early when the error stops shrinking (target out of reach for this pitch).
            size = float(np.linalg.norm(error))
            if size < best - 1e-5:
                best, stalled = size, 0
            else:
                stalled += 1
                if stalled > 12:
                    break
            jjt = j_task @ j_task.T + (damping ** 2) * np.eye(j_task.shape[0])
            dq = j_task.T @ np.linalg.solve(jjt, error)
            step = np.abs(dq).max()
            if step > 0.2:
                dq *= 0.2 / step
            q = self.clamp(q + dq)
        t = self.fk(q)
        err = float(np.linalg.norm(target - t[:3, 3]))
        ok = err < tolerance and (
            direction is None or np.linalg.norm(np.cross(t[:3, :3] @ tool_axis, direction)) < 0.03
        )
        return (q, err) if ok else (None, err)

    def solve(
        self,
        target,
        seed=None,
        pitches=PITCHES,
        position_only_fallback: bool = True,
        tolerance: float = 0.002,
        iterations: int = 150,
        tool_axis=(0.0, 0.0, 1.0),
    ) -> IKResult | None:
        """Joint angles that put the tip at `target` (x, y, z in the base frame), or None.

        `pitches` are tried in order: pi/2 points the gripper straight down, 0 keeps it level.
        `tool_axis` is the direction the gripper points, expressed in the tip frame.
        """
        target = np.asarray(target, dtype=float)
        tool_axis = np.asarray(tool_axis, dtype=float)
        n = len(self.joint_names)
        seeds = []
        if seed is not None:
            seeds.append(np.asarray(seed, dtype=float))
        # A few generic starting postures, already turned towards the target.
        base_xy = self._joints[0].origin[:2, 3]
        pan = math.atan2(target[1] - base_xy[1], target[0] - base_xy[0])
        for shape in ([0.0, -0.6, 0.9, 0.9], [0.0, 0.3, 0.3, 1.0], [0.0, 0.0, 0.0, 0.0]):
            s = np.zeros(n)
            s[: min(n, 4)] = shape[: min(n, 4)]
            s[0] = self._pan_sign * pan
            seeds.append(s)

        attempts = [(p, self.approach_direction(target, p)) for p in pitches]
        if position_only_fallback:
            attempts.append((None, None))
        for pitch, direction in attempts:
            for s in seeds:
                q, err = self._iterate(target, direction, s, iterations, tolerance, tool_axis)
                if q is not None:
                    return IKResult(q, pitch, err)
        return None
