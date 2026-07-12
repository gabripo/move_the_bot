# AI Agentic Implementation Plan: Spatial HMI Robotics Project
*System Architecture Standard*: All components must communicate asynchronously via ROS 2 topics.
*Target OS Phase 1*: macOS (M1/Apple Silicon) or Linux VM.
*Goal*: Build the logical and communication architecture using CPU-bound proxies and virtual visualization.

## Step 1.1: Environment & Workspace Initialization
Create a standard ROS 2 (Humble) Python workspace named `spatial_hmi_ws`. Initialize a package named `mock_hmi_core`. Generate the `setup.py`, `package.xml`, and the standard directory structure. Add dependencies for `rclpy`, `std_msgs`, `geometry_msgs`, `sensor_msgs`, and `visualization_msgs`.

## Step 1.2: Mock Perception Node (MediaPipe)
Write a ROS 2 Python node named `mediapipe_perception_node.py`. Use `cv2` to capture the standard webcam feed (device 0). Implement `mediapipe.solutions.hands` to extract the 3D landmark coordinates of the index fingertip and thumb tip. Calculate the midpoint between them. Publish this midpoint as a `geometry_msgs/msg/Point` to a topic named `/spatial_coords` at 30 Hz.

## Step 1.3: Virtual Scene & Voice Nodes (Optional/Bonus)
### Voice 
Write a ROS 2 Python node named `voice_command_node.py`. Use the `speech_recognition` library and local Whisper model to transcribe microphone input. Publish the transcribed text to a topic named `/voice_commands` as a `std_msgs/msg/String`.
### Scene
Write a ROS 2 Python node named `virtual_scene_node.py`. Publish a `visualization_msgs/msg/MarkerArray` to a topic named `/virtual_scene`. The array should contain a 3D cylinder (representing a coffee mug) with XYZ-coordinates relative to the base frame.

## Step 1.4: Agentic Reasoning Node (OpenClaw / Ollama)
Write a ROS 2 Python node named `agentic_core_node.py`. Subscribe to `/spatial_coords` and `/voice_commands`. Use the requests library to interface with a local Ollama server (http://localhost:11434/api/generate) running llama3. Maintain a state loop: if a voice command 'grab' is received, take the most recent (X, Y, Z) point from `/spatial_coords` and publish it to a topic named `/target_goal` as a `geometry_msgs/msg/Point`.

### Step 1.5: Mock Actuation & Visualization Node
Write a ROS 2 Python node named `mock_kinematics_node.py`. Subscribe to `/target_goal`. Write a basic 3-DOF Inverse Kinematics solver that calculates the base, shoulder, and elbow angles required to reach the target Point. Publish these angles to `/joint_states` using the `sensor_msgs/msg/JointState` format. Generate a basic URDF file for a 3-axis arm and an RViz2 launch file to visualize the joint states and the virtual scene markers."