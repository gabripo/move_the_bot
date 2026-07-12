import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from ros_nodes.kinematics import inverse_kinematics, L0, L1, L2


def test_reachable_point():
    result = inverse_kinematics(0.2, 0.0, 0.3)
    assert result is not None
    theta1, theta2, theta3 = result
    assert isinstance(theta1, float)
    assert isinstance(theta2, float)
    assert isinstance(theta3, float)


def test_reachable_symmetric():
    result = inverse_kinematics(0.0, 0.2, 0.2)
    assert result is not None
    theta1, theta2, theta3 = result
    assert abs(theta1 - math.pi / 2) < 0.01


def test_low_point():
    result = inverse_kinematics(0.15, 0.0, 0.05)
    assert result is not None


def test_high_point():
    result = inverse_kinematics(0.1, 0.0, 0.45)
    assert result is not None


def test_unreachable_too_far():
    result = inverse_kinematics(0.8, 0.0, 0.8)
    assert result is None


def test_unreachable_diagonal():
    result = inverse_kinematics(0.4, 0.4, 0.3)
    assert result is None


def test_unreachable_high_offset():
    result = inverse_kinematics(0.3, 0.4, 0.5)
    assert result is None


def test_negative_x_positive_y():
    result = inverse_kinematics(-0.2, 0.1, 0.2)
    assert result is not None
    theta1, theta2, theta3 = result
    assert theta1 > 0  # Quadrant II
    assert theta2 > 0


def test_ik_roundtrip():
    """Forward kinematics should approximately equal the input."""

    def forward(angles):
        t1, t2, t3 = angles
        x = math.cos(t1) * (L1 * math.sin(t2) + L2 * math.sin(t2 + t3))
        y = math.sin(t1) * (L1 * math.sin(t2) + L2 * math.sin(t2 + t3))
        z = L0 + L1 * math.cos(t2) + L2 * math.cos(t2 + t3)
        return (x, y, z)

    for target in [(0.2, 0.0, 0.3), (0.15, 0.1, 0.2), (-0.1, 0.15, 0.25)]:
        ik = inverse_kinematics(*target)
        assert ik is not None
        fk = forward(ik)
        for a, b in zip(target, fk):
            assert abs(a - b) < 0.01


def test_joint_limits():
    """All joint angles should be within reasonable limits."""
    targets = [(0.15, 0.1, 0.2), (-0.1, 0.2, 0.15), (0.0, 0.3, 0.1), (-0.2, 0.0, 0.35)]
    for target in targets:
        result = inverse_kinematics(*target)
        assert result is not None
        theta1, theta2, theta3 = result
        assert -math.pi <= theta1 <= math.pi
        assert -math.pi <= theta2 <= math.pi, f"theta2={theta2} out of range"
        assert 0 <= theta3 <= math.pi, f"theta3={theta3} out of range (elbow always bent up)"
