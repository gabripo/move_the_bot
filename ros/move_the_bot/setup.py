from glob import glob

from setuptools import find_packages, setup

package_name = "move_the_bot"

setup(
    name=package_name,
    version="2.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*")),
        ("share/" + package_name + "/config", glob("config/*")),
        ("share/" + package_name + "/robot", glob("robot/*.urdf") + glob("robot/*.xacro")),
        ("share/" + package_name + "/robot/meshes", glob("robot/meshes/*")),
        ("share/" + package_name + "/robot/collision", glob("robot/collision/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Gabriele Giardino",
    maintainer_email="gabripo93@gmail.com",
    description="Voice, gesture and text control of a robot arm through an LLM agent, MoveIt 2 and ros2_control.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "skill_server = move_the_bot.skill_server:main",
            "agent = move_the_bot.agent_node:main",
        ],
    },
)
