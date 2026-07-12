from setuptools import setup
from glob import glob
import os

package_name = "mock_hmi_core"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name, "ros_nodes", "models"],
    package_data={
        "models": ["builtin/*.json", "builtin/*.glb"],
    },
    include_package_data=True,
    data_files=[
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "launch"), glob("launch/*.rviz")),
        (os.path.join("share", package_name, "urdf"), glob("urdf/*")),
    ],
    install_requires=["setuptools", "requests", "transforms3d"],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "agentic_core = mock_hmi_core.agentic_core_node:main",
            "mock_kinematics = ros_nodes.mock_kinematics_node:main",
            "virtual_scene = ros_nodes.virtual_scene_node:main",
            "object_spawn = ros_nodes.object_spawn_node:main",
        ],
    },
)
