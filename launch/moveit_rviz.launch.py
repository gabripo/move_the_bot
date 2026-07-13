from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
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
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                "/ros_ws/src/mock_hmi_core/launch/move_group.launch.py"
            )
        ),
        Node(
            package="mock_hmi_core",
            executable="mock_motion_planning",
            output="screen",
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            name="rviz",
            output="screen",
            arguments=["-d", "/ros_ws/src/mock_hmi_core/launch/moveit.rviz"],
        ),
    ])
