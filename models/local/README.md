# Your own 3D models (not committed)

A GLB here named after an object, such as `mug.glb`, replaces the built-in model of that object
on your computer only: this folder is checked first (a webcam scan of the same name made
afterwards replaces it, see the docs), and git ignores everything in it except
this file. Use it for models you may not share, such as a scan of your own mug.

- Make the model the real size of the object, standing up (glTF is y-up); it is scaled to the
  object's height.
- From a photo: `python3 scripts/photo_to_3d.py --image my-mug.jpg --name mug` makes one with
  Idol (image to 3D) and puts it here. See [docs/your-own-objects.md](../../docs/your-own-objects.md).
- Rebuild the images afterwards: `./run.sh --rebuild`.
