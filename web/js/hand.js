// Hand control: the webcam watches one hand, and the robot's gripper follows it.
//
//   hand left / right on screen  ->  gripper left / right
//   hand up / down               ->  gripper up / down
//   hand closer to the camera    ->  gripper further forward
//   pinch thumb and index finger ->  close the gripper (around an object: grab it)
//
// Hand tracking runs in the browser with MediaPipe; no video leaves the computer.

import { openCamera } from "./camera.js";

// Resolved against the page, not this file: a bare "./vendor" in import() would mean js/vendor.
const LOCAL = new URL("vendor/mediapipe", document.baseURI).href;
const CDN_WASM = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/wasm";
const CDN_MODEL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
const BONES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11],
  [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17]];

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// A MediaPipe hand tracker for one hand in a video: from this server when it has the files
// (docker/web fetches them at build time), else from the CDN. GPU when the browser allows it.
let visionModule = null;
export async function loadHandLandmarker({ numHands = 1 } = {}) {
  visionModule ||= import(`${LOCAL}/vision_bundle.mjs`);
  const vision = await visionModule;
  const local = await fetch(`${LOCAL}/hand_landmarker.task`, { method: "HEAD" }).then((r) => r.ok).catch(() => false);
  const options = (model, delegate) => ({
    baseOptions: { modelAssetPath: model, delegate },
    runningMode: "VIDEO", numHands,
    minHandDetectionConfidence: 0.6, minHandPresenceConfidence: 0.6, minTrackingConfidence: 0.6,
  });
  const model = local ? `${LOCAL}/hand_landmarker.task` : CDN_MODEL;
  let files;
  try {
    files = await vision.FilesetResolver.forVisionTasks(`${LOCAL}/wasm`);
  } catch {
    files = await vision.FilesetResolver.forVisionTasks(CDN_WASM);
  }
  try {
    return await vision.HandLandmarker.createFromOptions(files, options(model, "GPU"));
  } catch {
    return await vision.HandLandmarker.createFromOptions(files, options(model, "CPU"));
  }
}

// A thumbs-up: the four fingers folded, the thumb pointing up above everything else.
export function isThumbsUp(lm) {
  if (!lm) return false;
  const d = (a, b) => Math.hypot(lm[a].x - lm[b].x, lm[a].y - lm[b].y);
  const palm = d(0, 9);                                  // wrist to middle knuckle: the hand's size
  if (!(palm > 0.03)) return false;
  // A folded finger's tip is no further from the wrist than its middle joint.
  const folded = [[8, 6], [12, 10], [16, 14], [20, 18]].every(([tip, joint]) => d(tip, 0) < 1.05 * d(joint, 0));
  const thumbUp = lm[4].y < lm[3].y && lm[3].y < lm[2].y && lm[2].y - lm[4].y > 0.45 * palm;
  const highest = [5, 6, 8, 9, 12, 13, 16, 17, 20].every((i) => lm[4].y < lm[i].y - 0.15 * palm);
  return folded && thumbUp && highest;
}

// Turns 21 hand landmarks (image coordinates 0..1, not mirrored) into a gripper target.
export class HandMapper {
  constructor() { this.reset(); }

  reset() {
    this.neutralSize = null;
    this.samples = [];
    this.smooth = null;
    this.pinch = 1;
  }

  update(landmarks, aspect = 4 / 3) {
    const p = (i) => landmarks[i];
    // The palm is steadier than the fingertips, which move when pinching.
    const palm = {
      x: (p(0).x + p(5).x + p(17).x) / 3,
      y: (p(0).y + p(5).y + p(17).y) / 3,
    };
    const distance = (a, b) => Math.hypot((a.x - b.x) * aspect, a.y - b.y);
    const size = distance(p(0), p(9));           // wrist to middle knuckle: bigger = closer
    if (!(size > 0.01)) return null;

    // The first half second sets the "neutral" distance of the hand from the camera.
    if (this.neutralSize === null) {
      this.samples.push(size);
      if (this.samples.length >= 8) {
        this.samples.sort((a, b) => a - b);
        this.neutralSize = this.samples[Math.floor(this.samples.length / 2)];
      }
    }
    const neutral = this.neutralSize ?? size;

    const screenX = 1 - palm.x;                   // mirrored, like the preview
    const target = {
      x: clamp(0.21 + 0.32 * (size / neutral - 1), 0.10, 0.36),
      y: clamp((0.5 - screenX) * 0.80, -0.27, 0.27),
      z: clamp(0.02 + ((0.85 - palm.y) / 0.65) * 0.28, 0.015, 0.31),
    };
    const a = 0.35;
    this.smooth = this.smooth
      ? { x: this.smooth.x + a * (target.x - this.smooth.x), y: this.smooth.y + a * (target.y - this.smooth.y),
          z: this.smooth.z + a * (target.z - this.smooth.z) }
      : target;

    // Pinch: fingertip distance relative to the hand size, so it works at any distance.
    const ratio = distance(p(4), p(8)) / size;
    const open = clamp((ratio - 0.28) / (0.95 - 0.28), 0, 1);
    this.pinch += 0.5 * (open - this.pinch);
    return { position: this.smooth, gripper: this.pinch };
  }
}

export class HandControl {
  constructor({ video, canvas, onTarget, onLost, onStatus }) {
    this.video = video;
    this.canvas = canvas;
    this.onTarget = onTarget;
    this.onLost = onLost;
    this.onStatus = onStatus;
    this.mapper = new HandMapper();
    this.active = false;
    this.landmarker = null;
    this.lastSeen = 0;
  }

  async start() {
    if (this.active) return;
    this.onStatus("Starting the camera…");
    const stream = await openCamera({ width: { ideal: 640 }, height: { ideal: 480 } });
    this.video.srcObject = stream;
    await this.video.play();
    this.active = true;
    this.mapper.reset();
    if (!this.landmarker) {
      this.onStatus("Loading hand tracking…");
      this.landmarker = await loadHandLandmarker();
    }
    this.onStatus("Show one hand to the camera");
    this._loop();
  }

  stop() {
    this.active = false;
    if (this.video.srcObject) this.video.srcObject.getTracks().forEach((t) => t.stop());
    this.video.srcObject = null;
    const ctx = this.canvas.getContext("2d");
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.onLost();
  }

  _loop() {
    if (!this.active) return;
    if (this.video.readyState >= 2 && this.landmarker) {
      const result = this.landmarker.detectForVideo(this.video, performance.now());
      const hand = result.landmarks && result.landmarks[0];
      this.feed(hand || null);
    }
    requestAnimationFrame(() => this._loop());
  }

  // Also called directly by tests, with synthetic landmarks.
  feed(landmarks) {
    this._draw(landmarks);
    if (!landmarks) {
      if (this.lastSeen && performance.now() - this.lastSeen > 600) {
        this.lastSeen = 0;
        this.onLost();
        this.onStatus("Show one hand to the camera");
      }
      return;
    }
    const aspect = (this.video.videoWidth || 4) / (this.video.videoHeight || 3);
    const target = this.mapper.update(landmarks, aspect);
    if (!target) return;
    if (!this.lastSeen) this.onStatus("Following your hand. Pinch to grab.");
    this.lastSeen = performance.now();
    this.onTarget(target);
  }

  _draw(landmarks) {
    const c = this.canvas, ctx = c.getContext("2d");
    c.width = c.clientWidth || 320;
    c.height = c.clientHeight || 240;
    ctx.clearRect(0, 0, c.width, c.height);
    if (!landmarks) return;
    const x = (l) => (1 - l.x) * c.width, y = (l) => l.y * c.height;   // mirrored
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(56,189,248,0.9)";
    for (const [a, b] of BONES) {
      ctx.beginPath();
      ctx.moveTo(x(landmarks[a]), y(landmarks[a]));
      ctx.lineTo(x(landmarks[b]), y(landmarks[b]));
      ctx.stroke();
    }
    const closed = this.mapper.pinch < 0.35;
    ctx.fillStyle = closed ? "#f97316" : "#ffffff";
    for (const i of [4, 8]) {
      ctx.beginPath();
      ctx.arc(x(landmarks[i]), y(landmarks[i]), closed ? 7 : 5, 0, 2 * Math.PI);
      ctx.fill();
    }
  }
}

// A synthetic open or pinched hand, for tests and screenshots: centre and size in image units.
export function fakeHand({ x = 0.5, y = 0.5, size = 0.18, pinch = false } = {}) {
  const lm = Array.from({ length: 21 }, () => ({ x, y, z: 0 }));
  const set = (i, dx, dy) => { lm[i] = { x: x + dx * size, y: y + dy * size, z: 0 }; };
  set(0, 0, 0.55);                       // wrist
  set(9, 0, -0.2);                       // middle knuckle (0.75 * size above the wrist)
  set(5, 0.25, -0.15); set(13, -0.2, -0.15); set(17, -0.4, -0.05);
  set(12, 0, -1.0); set(16, -0.25, -0.9); set(20, -0.5, -0.7);
  if (pinch) { set(4, 0.2, -0.55); set(8, 0.22, -0.6); } else { set(4, 0.75, -0.2); set(8, 0.3, -0.95); }
  for (const [tip, base] of [[8, 5], [12, 9], [16, 13], [20, 17], [4, 0]]) {
    for (let k = 1; k <= 2; k++) {
      const t = k / 3, i = tip - (3 - k);
      lm[i] = { x: lm[base].x + (lm[tip].x - lm[base].x) * t, y: lm[base].y + (lm[tip].y - lm[base].y) * t, z: 0 };
    }
  }
  lm[1] = { x: x + 0.35 * size, y: y + 0.3 * size, z: 0 };
  return lm;
}

// A synthetic thumbs-up (a fist seen from the side, thumb up), for tests.
export function fakeThumbsUp({ x = 0.5, y = 0.55, size = 0.18 } = {}) {
  const at = (dx, dy) => ({ x: x + dx * size, y: y + dy * size, z: 0 });
  const lm = Array.from({ length: 21 }, () => at(0, 0));
  lm[0] = at(0, 0.6);                                                   // wrist, below the fist
  lm[1] = at(-0.15, 0.35); lm[2] = at(-0.25, 0.05); lm[3] = at(-0.3, -0.35); lm[4] = at(-0.3, -0.75);
  // Each finger: knuckle, middle joint (furthest out), then curled back towards the palm.
  [[5, -0.1], [9, 0.05], [13, 0.2], [17, 0.35]].forEach(([base, dy]) => {
    lm[base] = at(0, dy - 0.4);
    lm[base + 1] = at(0.45, dy - 0.4);
    lm[base + 2] = at(0.45, dy - 0.15);
    lm[base + 3] = at(0.25, dy - 0.1);
  });
  return lm;
}
