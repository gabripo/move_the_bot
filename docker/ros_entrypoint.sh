#!/bin/bash
set -e

source /opt/ros/humble/setup.bash
source /ros_ws/install/setup.bash

# Pull the LLM model via Ollama HTTP API
# (ollama CLI launcher requires a TTY, so we use the API directly)
echo "Pulling model llama3.2..."
python3 -c "
import requests, json, time
url = '${OLLAMA_URL%/api/generate}/api/pull'
for attempt in range(30):
    try:
        r = requests.post(url, json={'name': 'llama3.2'}, timeout=300, stream=True)
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                data = json.loads(line)
                s = data.get('status', '')
                if s:
                    print(f'  {s}')
        print('Model ready')
        break
    except requests.exceptions.ConnectionError:
        if attempt < 29:
            time.sleep(2)
        else:
            print('Failed to connect to Ollama')
            exit(1)
"

exec "$@"
