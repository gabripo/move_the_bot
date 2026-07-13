#!/bin/bash
set -e

source /opt/ros/humble/setup.bash
source /ros_ws/install/setup.bash

echo "Pulling model ${OLLAMA_MODEL}..."
python3 -c "
import requests, json, time
url = '${OLLAMA_URL%/api/generate}/api/pull'
model = '${OLLAMA_MODEL}'
for attempt in range(30):
    try:
        r = requests.post(url, json={'name': model}, timeout=300, stream=True)
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
