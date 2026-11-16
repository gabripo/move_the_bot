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

- **Ollama on this computer:** install [Ollama](https://ollama.com) and start with
  `./run.sh --host-ollama`. Ollama supports the Radeon RX 9000 series on Linux through ROCm,
  and has a Vulkan back-end as an alternative ([Ollama GPU support](https://docs.ollama.com/gpu)).
- **Ollama on a GPU PC, the robot stack on a laptop:** see the next section.
- **In Docker:** `docker compose -f docker-compose.yml -f docker/compose.amd.yml --profile ollama up -d`
  uses the ROCm build of Ollama. This file was written from the documentation and has not been
  tested by the author.

With 16 GB of video memory you can use a larger model than the default, for better free-form
planning: set `OLLAMA_MODEL` in `.env`, for example `qwen2.5:14b-instruct-q4_K_M`.

## A GPU PC in your network

Run the language model on the computer with the GPU, and move_the_bot wherever you like (a
laptop, for example). Ollama has no password, so do this only in a network you trust and never
forward port 11434 on your router.

**On the GPU PC** (Linux with an AMD GPU; written for Bazzite, works on Fedora and others with
Podman). [`docker/ollama-server/ollama.container`](../docker/ollama-server/ollama.container)
runs the official ROCm build of Ollama as a service that starts at boot:

```bash
curl -fsSLO https://raw.githubusercontent.com/gabripo/move_the_bot/master/docker/ollama-server/ollama.container
sudo podman pull docker.io/ollama/ollama:rocm          # several GB, once
sudo cp ollama.container /etc/containers/systemd/
sudo systemctl daemon-reload
sudo systemctl start ollama

# Allow other computers in the network to connect (firewalld, as on Bazzite and Fedora)
sudo firewall-cmd --permanent --add-port=11434/tcp && sudo firewall-cmd --reload

# Download the model and check that it runs on the GPU
sudo podman exec ollama ollama pull qwen2.5:14b-instruct-q4_K_M
sudo podman exec ollama ollama run qwen2.5:14b-instruct-q4_K_M "Say hi" --verbose
sudo podman exec ollama ollama ps          # PROCESSOR should say 100% GPU
hostname -I                                # this PC's address in the network
```

If `ollama ps` shows CPU, look for the detected GPU in `sudo journalctl -u ollama | grep -i -E "gpu|rocm|amdgpu"`.
To use Vulkan instead of ROCm, change the image to `docker.io/ollama/ollama:latest` and remove
the `/dev/kfd` line.

**On the computer that runs move_the_bot**, with the address from `hostname -I`:

```bash
curl http://192.168.1.50:11434/api/version           # must answer
echo "OLLAMA_URL=http://192.168.1.50:11434" >> .env
echo "OLLAMA_MODEL=qwen2.5:14b-instruct-q4_K_M" >> .env
./run.sh
```

`./run.sh --ollama http://192.168.1.50:11434` does the same for one run. A name such as
`http://gaming-pc.local:11434` works too: `run.sh` turns it into an address, because containers
often cannot resolve `.local` names. Give the PC a fixed address in your router so it does not
change.

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
