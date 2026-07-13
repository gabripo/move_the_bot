from launch import LaunchDescription
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    moveit_config = (
        MoveItConfigsBuilder(robot_name="simple_arm", package_name="mock_hmi_core")
        .robot_description()
        .robot_description_semantic()
        .planning_pipelines(pipelines=["ompl"])
        .to_moveit_configs()
    )

    return LaunchDescription([
        Node(package="mock_hmi_core", executable="mock_motion_planning", output="screen"),
        Node(package="mock_hmi_core", executable="virtual_scene", output="screen"),
        Node(package="mock_hmi_core", executable="object_spawn", output="screen"),
        Node(package="mock_hmi_core", executable="joint_state_to_markers", output="screen"),
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
            parameters=[moveit_config.robot_description],
        ),
        Node(
            package="moveit_ros_move_group",
            executable="move_group",
            output="screen",
            parameters=[moveit_config.to_dict()],
        ),
    ])
