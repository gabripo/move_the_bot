# Your own 3D models (not committed)

A GLB here named after an object, such as `mug.glb`, replaces the built-in model of that object
on your computer only: this folder is checked first, and git ignores everything in it except
this file. Use it for models you may not share, such as a scan of your own mug.

- Make the model the real size of the object, standing up (glTF is y-up); it is scaled to the
  object's height.
- Point clouds work too, such as an image-to-3D Gaussian splat converted to coloured points
  (`mode` 0 with `COLOR_0`).
- Rebuild the images afterwards: `./run.sh --rebuild`.
