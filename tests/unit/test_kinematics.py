"""Forward and inverse kinematics of the SO-101, computed from its URDF."""
import math
from pathlib import Path

import numpy as np
import pytest

from move_the_bot.kinematics import PITCHES, Chain

URDF = Path(__file__).resolve().parents[2] / "ros" / "move_the_bot" / "robot" / "so101.urdf"


@pytest.fixture(scope="module")
def chain():
    return Chain.from_urdf(URDF.read_text(), "base_link", "gripper_frame_link")


def test_chain_is_read_from_the_urdf(chain):
    assert chain.joint_names == ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
    assert np.all(chain.lower < chain.upper)


def test_forward_kinematics_is_a_rigid_transform(chain):
    pose = chain.fk(np.array([0.3, -0.5, 0.4, 0.8, 0.1]))
    rotation = pose[:3, :3]
    assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-9)
    assert np.linalg.det(rotation) == pytest.approx(1.0)


def test_shoulder_pan_turns_the_arm_about_the_vertical_axis(chain):
    q = np.array([0.0, -0.5, 0.4, 0.8, 0.0])
    a, b = chain.position(q), chain.position(q + np.array([0.4, 0, 0, 0, 0]))
    assert a[2] == pytest.approx(b[2], abs=1e-6)


@pytest.mark.parametrize("target", [
    (0.20, 0.00, 0.03), (0.25, 0.10, 0.05), (0.18, -0.15, 0.10), (0.30, 0.00, 0.08), (0.15, 0.12, 0.20),
])
def test_inverse_kinematics_reaches_the_target(chain, target):
    result = chain.solve(target)
    assert result is not None
    assert np.linalg.norm(chain.position(result.joints) - np.array(target)) < 0.003
    assert np.all(result.joints >= chain.lower - 1e-9) and np.all(result.joints <= chain.upper + 1e-9)


def test_low_grasps_point_the_gripper_down(chain):
    result = chain.solve((0.20, 0.0, 0.03))
    assert result.pitch == pytest.approx(math.pi / 2)
    tool_axis = chain.fk(result.joints)[:3, 2]
    assert tool_axis[2] < -0.98


def test_requested_pitch_is_respected(chain):
    result = chain.solve((0.22, 0.0, 0.12), pitches=(math.radians(45),), position_only_fallback=False)
    assert result is not None
    tool_axis = chain.fk(result.joints)[:3, 2]
    assert math.asin(-tool_axis[2]) == pytest.approx(math.radians(45), abs=0.03)


def test_unreachable_targets_return_none(chain):
    assert chain.solve((0.80, 0.0, 0.10)) is None
    assert chain.solve((0.20, 0.0, 0.90)) is None


def test_pitch_list_goes_from_straight_down_to_horizontal():
    assert PITCHES[0] == pytest.approx(math.pi / 2) and PITCHES[-1] == 0.0
    assert list(PITCHES) == sorted(PITCHES, reverse=True)
