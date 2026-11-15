"""Start the whole robot side of move_the_bot.

  ros2 launch move_the_bot bringup.launch.py                  # simulated arm (mock hardware)
  ros2 launch move_the_bot bringup.launch.py hardware:=isaac  # arm simulated in NVIDIA Isaac Sim
  ros2 launch move_the_bot bringup.launch.py hardware:=real   # real SO-101 on USB

What runs:
  robot_state_publisher   publishes the robot model and its link positions
  ros2_control_node       the controller manager, with the chosen hardware plugin
  controller spawners     joint_state_broadcaster, arm_controller, gripper_controller
  move_group              MoveIt 2: collision-aware planning and trajectory execution
  skill_server            pick, place, move, spawn... plus hand teleoperation
  agent                   turns typed or spoken requests into skills (rules first, then an LLM)
  rosbridge_websocket     lets the browser talk to ROS
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


DEFAULT_CALIBRATION = "/calibration/so101.yaml"


def _setup(context):
    share = get_package_share_directory("move_the_bot")
    hardware = LaunchConfiguration("hardware").perform(context)
    usb_port = LaunchConfiguration("usb_port").perform(context)
    calibration = LaunchConfiguration("calibration").perform(context)
    if not calibration and os.path.isfile(DEFAULT_CALIBRATION):
        calibration = DEFAULT_CALIBRATION      # mounted by docker/compose.real.yml

    moveit = (
        MoveItConfigsBuilder("so101", package_name="move_the_bot")
        .robot_description(
            file_path="robot/so101.urdf.xacro",
            mappings={
                "hardware": hardware,
                "usb_port": usb_port,
                "joint_config_file": calibration,
            },
        )
        .robot_description_semantic(file_path="config/so101.srdf")
        .robot_description_kinematics(file_path="config/kinematics.yaml")
        .joint_limits(file_path="config/joint_limits.yaml")
        .trajectory_execution(file_path="config/moveit_controllers.yaml")
        .pilz_cartesian_limits(file_path="config/pilz_cartesian_limits.yaml")
        .planning_pipelines(
            pipelines=["pilz_industrial_motion_planner", "ompl"],
            default_planning_pipeline="pilz_industrial_motion_planner",
        )
        .planning_scene_monitor(
            publish_robot_description=True, publish_robot_description_semantic=True
        )
        .to_moveit_configs()
    )

    controllers = os.path.join(share, "config", "ros2_controllers.yaml")

    nodes = [
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            parameters=[moveit.robot_description],
            output="screen",
        ),
        Node(
            package="controller_manager",
            executable="ros2_control_node",
            parameters=[controllers],
            remappings=[("~/robot_description", "/robot_description")],
            output="screen",
        ),
        Node(
            package="controller_manager",
            executable="spawner",
            arguments=[
                "joint_state_broadcaster",
                "arm_controller",
                "gripper_controller",
                "--controller-manager-timeout",
                "60",
            ],
            output="screen",
        ),
        Node(
            package="moveit_ros_move_group",
            executable="move_group",
            parameters=[
                moveit.to_dict(),
                {
                    # The mock arm reaches every waypoint instantly; real servos lag a little.
                    "trajectory_execution.allowed_execution_duration_scaling": 3.0,
                    "trajectory_execution.allowed_goal_duration_margin": 2.0,
                    "trajectory_execution.allowed_start_tolerance": 0.05,
                },
            ],
            output="screen",
        ),
        Node(
            package="move_the_bot",
            executable="skill_server",
            parameters=[
                moveit.robot_description,
                {"models_dir": LaunchConfiguration("models_dir")},
            ],
            output="screen",
            respawn=True,
            respawn_delay=2.0,
        ),
        Node(
            package="move_the_bot",
            executable="agent",
            condition=IfCondition(LaunchConfiguration("agent")),
            output="screen",
            respawn=True,
            respawn_delay=2.0,
        ),
        Node(
            package="rosbridge_server",
            executable="rosbridge_websocket",
            parameters=[{"port": 9090, "address": "", "send_action_goals_in_new_thread": True}],
            condition=IfCondition(LaunchConfiguration("rosbridge")),
            output="log",
        ),
    ]
    return nodes


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "hardware",
                default_value="mock",
                choices=["mock", "isaac", "real"],
                description="Where joint commands go: mock (simulated), isaac (Isaac Sim) or real (SO-101 on USB).",
            ),
            DeclareLaunchArgument(
                "usb_port", default_value="/dev/ttyACM0", description="Serial port of the real arm."
            ),
            DeclareLaunchArgument(
                "calibration",
                default_value="",
                description="YAML file with the real arm's servo calibration (see config/so101_calibration.example.yaml).",
            ),
            DeclareLaunchArgument(
                "agent", default_value="true", description="Start the language agent in this launch."
            ),
            DeclareLaunchArgument(
                "rosbridge", default_value="true", description="Start the websocket bridge for the browser."
            ),
            DeclareLaunchArgument(
                "models_dir",
                default_value=os.environ.get("MODELS_DIR", "/models"),
                description="Folder with builtin/ and cache/ 3D models of the objects.",
            ),
            OpaqueFunction(function=_setup),
        ]
    )
