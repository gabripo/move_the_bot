When the user asks to create, place, spawn, or add an object:

1. Identify the object name from the command.
2. Determine the position:
   - If "middle" or "center" → (0.2, 0.0, 0.05)
   - If "left" → current position with x -= 0.15
   - If "right" → current position with x += 0.15
   - If "here" or no position → use current hand position
   - If explicit numbers → parse them (order: x y z)
3. Respond with:
   {"action": "spawn", "object": "object_name", "target": {"x": ..., "y": ..., "z": ...}}

Known object names: apple, mug, coffee mug, bottle, cube, sphere, ball, table, cylinder, can
If the object name is unknown, still attempt to spawn it — the system will
report if a 3D model is not available.
