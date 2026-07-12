from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package="mock_hmi_core", executable="mock_kinematics", output="screen"),
        Node(package="mock_hmi_core", executable="virtual_scene", output="screen"),
        Node(package="mock_hmi_core", executable="object_spawn", output="screen"),
        Node(
            package="rosbridge_server",
            executable="rosbridge_websocket",
            output="screen",
            parameters=[{"port": 9090}],
        ),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            output="screen",
            parameters=[{"robot_description": open("/ros_ws/src/mock_hmi_core/urdf/simple_arm.urdf").read()}],
        ),
    ])
