import sys
from pathlib import Path

# The Python package lives inside the ROS package; the pure-Python parts need no ROS to test.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ros" / "move_the_bot"))
