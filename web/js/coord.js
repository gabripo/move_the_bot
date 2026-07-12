/* Coordinate conversion between Three.js and IK frames.
 *
 * Three.js: x=right, y=up, z=toward-viewer
 *      IK:  x=forward, y=left, z=up
 */

function threejs_to_ik(x, y, z) {
  return [z, x, y];
}

function ik_to_threejs(x, y, z) {
  return [y, z, x];
}
