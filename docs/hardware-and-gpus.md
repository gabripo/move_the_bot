# What runs on which computer

Short version: **this project runs on anything that runs Docker.** A GPU only makes the
language model faster. NVIDIA hardware is needed only for the NVIDIA components you might add
later.

| | Mac (Apple Silicon) | PC with AMD GPU (e.g. RX 9070 XT) | PC with NVIDIA RTX GPU | Jetson |
|---|---|---|---|---|
| Robot stack: ROS 2, MoveIt, ros2_control, web app | yes | yes | yes | yes |
| Hand tracking (runs in the browser) | yes | yes | yes | from a laptop's browser |
| Local language model on the GPU (Ollama) | yes, `--host-ollama` | yes, see below | yes | small models |
| NVIDIA NIM language models (cloud) | yes | yes | yes | yes |
| Real SO-101 over USB | native ROS or a Linux VM | yes (Linux) | yes (Linux) | yes |
| Isaac Sim | no | **no** | yes | no |
| Isaac ROS (cuMotion, FoundationPose) | no | **no** | yes | yes |
| GR00T fine-tuning | no | **no** | yes (enough VRAM) | no (inference only) |

## AMD GPU

Everything in this repository works. For the language model on the GPU:

- **Easiest:** install [Ollama](https://ollama.com) on the host and start with
  `./run.sh --host-ollama`. Ollama supports recent Radeon cards on Linux through ROCm, and has
  a Vulkan back-end as an alternative ([Ollama GPU support](https://docs.ollama.com/gpu)).
  On an immutable Linux such as Bazzite, install it in your home folder or run the
  `ollama/ollama:rocm` container with Podman.
- **In Docker:** `docker compose -f docker-compose.yml -f docker/compose.amd.yml --profile ollama up -d`
  uses the ROCm build of Ollama. This file was written from the documentation and has not been
  tested by the author.

With 16 GB of video memory you can use a larger model than the default, for better free-form
planning: set `OLLAMA_MODEL` in `.env` (for example a 7-14 billion parameter instruct model).

What an AMD GPU cannot run is the NVIDIA-only software. Isaac Sim requires an NVIDIA RTX GPU
([requirements](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html));
Isaac ROS and GR00T depend on CUDA.

## Using the NVIDIA parts without owning NVIDIA hardware

| Goal | Option |
|---|---|
| NVIDIA-hosted language models | NIM: `./run.sh --nim` with a free API key |
| Try Isaac Sim | rent a cloud machine with an RTX-class GPU by the hour (Isaac Sim is published for the major clouds) and connect this stack to it; or use NVIDIA's hosted learning labs |
| Fine-tune GR00T | a rented cloud GPU for the hours of training; inference later on a Jetson |
| Develop meanwhile | `HARDWARE=isaac` with the `joint_echo` stand-in exercises the same interface Isaac Sim uses |

## If you buy NVIDIA hardware later

| For | Hardware |
|---|---|
| Isaac Sim on your desk | a PC with a GeForce RTX card; check the current minimum in the requirements linked above |
| Running next to a real arm (cuMotion, perception, GR00T inference) | a Jetson Orin-class board |

A real SO-101 does not need either: it works with any Linux computer.

## Speed without a GPU

The built-in rules answer instantly on any machine. Only free-form requests wait for the
language model: a few seconds on a GPU, up to a minute on a laptop CPU inside Docker. NIM or
`--host-ollama` avoids the wait.
