import pytest


def _rclpy_available():
    try:
        import rclpy
        return True
    except ImportError:
        return False


requires_rclpy = pytest.mark.skipif(
    not _rclpy_available(),
    reason="rclpy not available (ROS 2 not installed on host)",
)
