# Testing

Everything GitHub runs on a pull request also runs on your own computer. This page goes from
the quickest check to the slowest. It was written and checked on a MacBook Air (Apple Silicon,
Docker Desktop); the commands are the same on Linux.

| | What it checks | Needs | Time |
|---|---|---|---|
| [1. Unit tests](#1-unit-tests) | language rules, skill validation, parsing of language-model answers, world model, kinematics | Python 3 (GitHub uses 3.12) | 2 s |
| [2. Robot tests](#2-robot-tests-end-to-end) | the real ROS stack: MoveIt plans, ros2_control executes. Pick and place, stacking, obstacles, stop, the agent, hand control | the running stack | 2 min |
| [3. Browser test](#3-browser-test) | the real page: 3D robot, commands, buttons, hand control with a scripted hand, no JavaScript errors | the running stack, Node 20 or newer | 1.5 min |
| [4. Isaac Sim interface](#4-isaac-sim-interface-test) | the robot tests through the topic-based hardware interface, with a small node playing Isaac Sim | Docker | 1 min |
| [5. By hand](#5-by-hand) | the language model, your webcam, your microphone | the running stack | a few minutes |

## Before you start

Start the stack and open http://localhost:8080. Wait until "Connected" and "Robot ready" are
green (about 20 s after the containers start):

```bash
./run.sh
```

Any language-model option works (`--host-ollama`, `--ollama URL`, `--nim`, `--no-llm`). The
automated tests only use the built-in rules, so they pass with or without a model; GitHub runs
them without one.

## 1. Unit tests

No Docker and no ROS needed. Once, in the repository folder:

```bash
python3 -m venv .venv
.venv/bin/pip install numpy requests pytest
```

Then:

```bash
.venv/bin/python -m pytest tests/unit
```

On Windows, use `.venv\Scripts\python` instead of `.venv/bin/python`. Add `-k NAME` to run only
the tests whose name contains `NAME`.

## 2. Robot tests (end to end)

These send real requests to the running robot container and check what the arm did. They move
the arm and clear the table, so don't run them while you record a demo.

```bash
docker compose exec -T robot /ros_entrypoint.sh pytest -v -p no:cacheprovider /ros_ws/tests/e2e/test_robot.py
```

- **The tests are copied into the robot image when it is built.** After you change a test, or
  any code under `ros/`, rebuild the robot container first, or you will test the old version:

  ```bash
  docker compose up -d --build --no-deps robot
  ```

  Then wait for "Robot ready" in `./run.sh logs` (about 20 s).
- Run one test with `-k`, for example `-k stop_interrupts`.
- `-p no:cacheprovider` keeps pytest from writing its cache into the container.

## 3. Browser test

Opens the page in a headless Chromium and uses it like a person would. Once:

```bash
cd tests/e2e && npm install && npx playwright install chromium
```

Then, from `tests/e2e`:

```bash
CHECK_HAND_TRACKING=1 node browser_test.mjs
```

- `CHECK_HAND_TRACKING=1` also checks that the MediaPipe hand-tracking model loads in the page.
- The test opens http://localhost:8080. Set `BASE_URL` to test another address.
- After you change anything in `web/`, rebuild the web container:

  ```bash
  docker compose up -d --build --no-deps web
  ```

## 4. Isaac Sim interface test

The same robot tests, with the hardware interface that talks to Isaac Sim: joint commands go
out on one ROS topic and joint states come back on another. `joint_echo` plays Isaac Sim's part:
every joint follows its command with a little lag. This replaces the normal stack until you
start it again.

```bash
docker compose down
HARDWARE=isaac docker compose up -d robot
docker compose exec -d robot /ros_entrypoint.sh ros2 run move_the_bot joint_echo
```

Start `joint_echo` right away: without it the arm reports no joint states and never becomes
ready. The tests wait for the robot by themselves:

```bash
docker compose exec -T robot /ros_entrypoint.sh pytest -v -p no:cacheprovider /ros_ws/tests/e2e/test_robot.py \
  -k "starts_at_home or pick_and_place or stack_one or plans_around or teleoperation_grabs"
```

Back to the normal stack:

```bash
docker compose down && ./run.sh
```

## 5. By hand

What the automated tests cannot cover:

| Check | How | Expected |
|---|---|---|
| The language model | Type `I'm thirsty` (with a mug on the table) | The conversation shows "Model plan (… s): pick mug → place at center" and the arm moves the mug |
| Every command through the model | Open **Settings** under the conversation, tick "Always ask the language model", type `put the apple on the cube` | The same result as with the rules, a little slower |
| Your webcam | Click **Hand control**, allow the camera, move your hand slowly, pinch over an object | The gripper follows your hand; a pinch grabs, opening lets go |
| Your microphone | Click the microphone, say `go home` | The command appears in the conversation and the arm goes home |
| Stop | Type `move the cube to the left`, click **Stop** while the arm moves, then **Home** at once | The arm stops, then goes home |

GitHub never calls a real language model. The unit tests in `tests/unit/test_llm.py` check the
prompts and how answers are read and validated, with the network mocked.

## What GitHub runs

`.github/workflows/tests.yml`, on every pull request and every push to `master`:

| Job | Steps |
|---|---|
| Unit tests | level 1, with Python 3.12 |
| End to end | builds the images, starts them without a language model, then levels 2, 3 (with hand tracking) and 4 |

`.github/workflows/screenshots.yml` runs after every change to `master`: it plays a fixed demo
in a headless browser and commits the pictures and the clip in `docs/media/`. See
[development.md](development.md#screenshots-and-the-demo-clip) to run it yourself.

## When a test fails

| Symptom | Cause, and what to do |
|---|---|
| Many robot tests fail with "MoveIt did not answer" | MoveIt's `move_group` process has stopped. Look for the reason with `docker compose logs robot \| grep -B5 "process has died"`, then restart it with `docker compose restart robot`. |
| "timed out waiting for MoveIt and the controllers" | The stack is still starting. Wait for "Robot ready" in `./run.sh logs`. |
| A test you changed behaves as before | The robot image still has the old tests: rebuild it (see level 2). |
| A test fails only now and then | Run it alone a few times to see how often: `for i in 1 2 3 4 5 6 7 8 9 10; do docker compose exec -T robot /ros_entrypoint.sh pytest -q -p no:cacheprovider /ros_ws/tests/e2e/test_robot.py -k NAME; done` |
| The browser test cannot connect | The web container is not running (`docker compose ps`), or `BASE_URL` points elsewhere. |
