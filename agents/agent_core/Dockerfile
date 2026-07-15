FROM ros:humble-ros-base

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install requests

COPY constants.py agentic_core_node.py tools.py /app/
COPY prompts/ /app/prompts/

RUN printf '#!/bin/bash\nset -e\nsource /opt/ros/humble/setup.bash\nexec python3 /app/agentic_core_node.py "$@"\n' > /ros_entrypoint.sh && \
    chmod +x /ros_entrypoint.sh

ENTRYPOINT ["/ros_entrypoint.sh"]
