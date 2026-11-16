# Development

## Day to day

```bash
./run.sh --rebuild        # after changing code
./run.sh logs             # the robot's log
docker compose exec robot /ros_entrypoint.sh bash     # a shell with ROS ready
```

Useful inside that shell:

```bash
ros2 control list_controllers          # arm_controller and gripper_controller should be active
ros2 topic echo /skill/status          # what the skill server is doing
ros2 topic echo /agent_log             # what the agent understood
ros2 topic pub --once /voice_commands std_msgs/String '{data: "create an apple"}'
```

## Without Docker

On Ubuntu 24.04 with ROS 2 Jazzy installed:

```bash
sudo apt install ros-jazzy-moveit ros-jazzy-ros2-control ros-jazzy-ros2-controllers \
  ros-jazzy-pilz-industrial-motion-planner ros-jazzy-rosbridge-server ros-jazzy-xacro
mkdir -p ~/ws/src && ln -s "$PWD/ros/move_the_bot" ~/ws/src/
cd ~/ws && colcon build --symlink-install && source install/setup.bash
ros2 launch move_the_bot bringup.launch.py models_dir:=/path/to/move_the_bot/models
```

For the web app, download its libraries once and serve the folder:

```bash
cd web && ./vendor.sh && python3 -m http.server 8080
```

Then open `http://localhost:8080/?ws=ws://localhost:9090`. The robot's meshes are read from
`web/robot/`; link them with `ln -s ../ros/move_the_bot/robot web/robot`.

## Tests

[testing.md](testing.md) shows how to run every test on your own computer: the unit tests, the
robot tests against the running stack, the browser test and the Isaac Sim interface test, plus
what to check by hand.

## Screenshots and the demo clip

`.github/workflows/screenshots.yml` runs after every change to the code on the main branch. It
starts the containers, plays a fixed script in a headless browser (`tests/e2e/screenshots.mjs`)
and commits the pictures and the clip to `docs/media/`. To change what is shown, edit that
script. To run it yourself:

```bash
cd tests/e2e && npm install && npx playwright install chromium
node screenshots.mjs            # writes ../../docs/media/*.png and demo.webm
```

The hand-control pictures use a scripted hand (`fakeHand` in `web/js/hand.js`), because there
is no webcam in CI. The rest of the path, from hand position to joint motion, is the real one.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Every command fails with "MoveIt did not answer" | MoveIt's `move_group` process has stopped. `docker compose logs robot \| grep -B5 "process has died"` shows why; `docker compose restart robot` starts it again. |
| The page shows "Disconnected" | The robot container is still starting (about 20 s), or has stopped: `./run.sh logs`. |
| "Model" stays yellow | The language model is still downloading or loading. Rule-based commands work meanwhile. `docker compose logs ollama`. |
| Free-form requests take a minute | The model runs on the CPU. See [hardware-and-gpus.md](hardware-and-gpus.md). |
| The microphone button does nothing | Use Chrome or Edge, or start with `--voice` for local speech-to-text. The page must be opened as `localhost` (or over https) for the browser to allow the microphone and camera. |
| Hand control does not start | Allow the camera for the page. The hand-tracking model is downloaded on first use, so that step needs internet. |
| "cannot reach x=… y=… z=…" | The place is outside the arm's reach (the light blue area on the table) or too high. |
| "something is in the way" | MoveIt found no collision-free path. Move or remove an object. |
| Port 8080 is taken | `WEB_PORT=8081` in `.env`. |
