// The object scanner (optional, ./run.sh --scan): show an object to the webcam, give it a name
// and its height, and it becomes an object on the table. The photos go to the scan service
// (docker/scan_server.py), where Idol turns them into 3D, on a GPU; then "create a <name>" places
// it. The Scan button only appears when the scan service answers.
//
// What the camera takes (the more sides Idol sees, the less of the object it has to invent):
//   1 photo   the fastest; Idol guesses the back
//   4 sides   a photo, then a quarter turn of the object, four times; fused into one model
//   video     one slow turn of the object, about 8 s; the sharpest frame of each quarter is used
//
// Starting: the Start button, the Space key, a thumbs-up to the camera, or saying (or typing)
// "scan my mug" / "scan a stapler, 8 cm". A countdown leaves time to show the object. Between
// photos the next one comes by itself after a few seconds; Space or "next" takes it at once.

import { openCamera } from "./camera.js";
import { isThumbsUp, loadHandLandmarker } from "./hand.js";

const $ = (id) => document.getElementById(id);
const COUNTDOWN = 3;            // seconds to show the object before the first photo
const BETWEEN = 4;              // seconds to turn it between photos
const VIDEO_SECONDS = 8;        // one turn, in video mode
const STEPS = {
  starting: "Starting", sending: "Sending the photos to the GPU", loading: "Loading Idol on the GPU",
  fusing: "Putting the sides together", model: "Making the 3D model",
};

export class Scanner {
  constructor({ send, onEvent }) {
    this.send = send;
    this.onEvent = onEvent || (() => {});
    this.health = null;
    this.stream = null;
    this.state = "closed";      // closed | ready | capturing | working
    this.skip = null;           // resolves the wait for the next photo early
    this.hands = null;
    this.thumbSince = 0;
    this.thumbLast = 0;
    $("btn-scan").addEventListener("click", () => this.open());
    $("scan-cancel").addEventListener("click", () => this.close());
    $("scan-form").addEventListener("submit", (e) => { e.preventDefault(); this.trigger(); });
    window.addEventListener("keydown", (e) => {
      if (this.state === "closed" || e.key !== " " || e.target.tagName === "INPUT") return;
      e.preventDefault();
      this.trigger();
    });
    this._check();
    // Again every 30 s: the scanner, or the GPU PC it uses, may be switched on or off meanwhile.
    setInterval(() => this._check(), 30000);
  }

  get mode() { return document.querySelector("input[name=scan-mode]:checked")?.value || "photo"; }

  // On the GPU PC (or this machine's GPU), not Idol's public demo or a test file.
  get onGpu() { return ["remote", "local"].includes(this.health?.backend); }

  async _check() {
    let health = null;
    try {
      const r = await fetch("./scan/health", { cache: "no-store" });
      health = r.ok ? await r.json() : null;
    } catch { /* no scanner */ }
    const ok = !!(health && health.ok);
    $("btn-scan").hidden = !ok;
    if (!ok) return;
    const first = !this.health;
    this.health = health;
    $("btn-scan").title = `Turn an object you show to the webcam into a 3D object (Idol, ${health.where})`;
    // Idol's public demo takes one photo (its free quota is small): no several-photo modes.
    const many = health.backend !== "demo";
    for (const id of ["scan-mode-sides", "scan-mode-video"]) $(id).disabled = !many;
    if (first || !many) $(many ? "scan-mode-sides" : "scan-mode-photo").checked = true;
  }

  // ------------------------------------------------------------ open, close, start

  async open({ name = "", height = null, start = false } = {}) {
    if (this.state === "working") return;
    if (name) $("scan-name").value = name;
    if (height) $("scan-height").value = String(height);
    if (this.state === "closed") {
      this.state = "ready";
      $("scan-panel").hidden = false;
      $("scan-thumbs").replaceChildren();
      this._overlay("");
      this._status("Hold the object inside the square, on a plain background. Start: the button, Space, a 👍 or say “scan …”.");
      if (!name) $("scan-name").focus();
      try {
        this.stream = await openCamera({ width: { ideal: 1280 }, height: { ideal: 720 } });
        $("scan-cam").srcObject = this.stream;
        await $("scan-cam").play().catch(() => {});
        this._watchHands();
      } catch (e) {
        this._status(e && e.name === "NotAllowedError" ? "The camera is blocked: allow it, then try again."
          : `The camera did not start: ${(e && e.message) || e}`, "error");
        return;
      }
    }
    if (start) this.trigger();
  }

  close() {
    if (this.state === "working") return;          // the GPU is busy; the result still arrives
    this.state = "closed";
    this.skip?.();
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
    $("scan-cam").srcObject = null;
    $("scan-panel").hidden = true;
  }

  // The button, Space, "next", a thumbs-up: start, or take the next photo now.
  trigger() {
    if (this.state === "ready" && !this.starting) this._run();
    else if (this.state === "capturing") this.skip?.();
  }

  // Words from the command box or the microphone. True when they were for the scanner.
  command(text) {
    const t = text.trim().toLowerCase().replace(/[.!?]+$/, "");
    if (this.state === "capturing" && /^(next|photo|cheese|snap|take it|now|go)\b/.test(t)) { this.trigger(); return true; }
    if (this.state !== "closed" && /^(cancel|close)( the)?( scan(ner)?)?$/.test(t)) { this.close(); return true; }
    const m = t.match(/^(?:please\s+)?(?:scan|digiti[sz]e|virtuali[sz]e)(?:\s+(.*))?$/);
    if (!m || $("btn-scan").hidden) return false;
    let what = (m[1] || "").replace(/^(this|my|the|a|an)\s+/, "");
    const cm = what.match(/,?\s*(\d+(?:\.\d+)?)\s*(?:cm|centimet(?:er|re)s?)\s*(?:tall|high)?$/);
    if (cm) what = what.slice(0, cm.index);
    this.open({ name: what.trim(), height: cm ? parseFloat(cm[1]) : null, start: !!what.trim() });
    return true;
  }

  async _run() {
    const name = $("scan-name").value.trim();
    if (!name) { this._status("Give it a name first.", "error"); $("scan-name").focus(); return; }
    this.starting = true;
    for (let t = 0; t < 30 && !$("scan-cam").videoWidth; t++) await new Promise((r) => setTimeout(r, 100));
    this.starting = false;
    if (this.state !== "ready") return;
    if (!$("scan-cam").videoWidth) { this._status("No picture from the camera yet.", "error"); return; }
    this.state = "capturing";
    $("scan-go").disabled = true;
    $("scan-thumbs").replaceChildren();
    const mode = this.mode;
    let photos = null;
    try {
      photos = mode === "video" ? await this._video(name) : await this._photos(name, mode === "sides" ? 4 : 1);
    } finally {
      $("scan-go").disabled = false;
      this._overlay("");
    }
    if (this.state !== "capturing" || !photos) return;     // cancelled
    await this._upload(name, photos);
  }

  // ------------------------------------------------------------ taking the photos

  async _photos(name, shots) {
    const photos = [];
    for (let k = 0; k < shots; k++) {
      this.onEvent("capture", { name, shot: k + 1, shots, mode: shots > 1 ? "sides" : "photo" });
      if (k === 0) {
        this._status(shots > 1 ? "Photo 1 of 4: the front." : "Hold it still…");
      } else {
        this._status(`Photo ${k + 1} of ${shots}: turn it a quarter turn, the same way each time. Space or “next” when it is ready.`);
      }
      if (!(await this._countdown(k === 0 ? COUNTDOWN : BETWEEN, k === 0 ? "" : "↻ a quarter turn"))) return null;
      photos.push(this._shot());
      this._flash();
      this._thumb(photos.at(-1));
    }
    return photos;
  }

  // One slow turn on video; from each quarter of it, the sharpest frame (the least motion blur).
  async _video(name) {
    this.onEvent("capture", { name, shot: 0, shots: 4, mode: "video" });
    this._status("When the countdown ends, turn it slowly once all the way round (about 8 s).");
    if (!(await this._countdown(COUNTDOWN, ""))) return null;
    const best = [null, null, null, null];
    const near = VIDEO_SECONDS / 16;               // each photo: within this many seconds of its quarter
    const start = performance.now();
    const small = document.createElement("canvas");
    small.width = small.height = 160;
    while (this.state === "capturing") {
      const t = (performance.now() - start) / 1000;
      if (t >= VIDEO_SECONDS) break;
      this._overlay(`<span class="rec-dot"></span>${Math.ceil(VIDEO_SECONDS - t)} s<br><small>↻ keep turning</small>`, "video");
      $("scan-progress").style.width = `${(100 * t) / VIDEO_SECONDS}%`;
      const quarter = Math.round(t / (VIDEO_SECONDS / 4));
      if (quarter < 4 && Math.abs(t - quarter * (VIDEO_SECONDS / 4)) <= near) {
        const sharp = this._sharpness(small);
        if (!best[quarter] || sharp > best[quarter].sharp) best[quarter] = { sharp, photo: this._shot() };
        if (!best[quarter].shown && t > quarter * (VIDEO_SECONDS / 4) + near - 0.1) {
          best[quarter].shown = true;
          this._thumb(best[quarter].photo);
          this.onEvent("capture", { name, shot: quarter + 1, shots: 4, mode: "video" });
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
    $("scan-progress").style.width = "0";
    if (this.state !== "capturing") return null;
    const photos = best.filter(Boolean).map((b) => b.photo);
    $("scan-thumbs").replaceChildren();
    photos.forEach((p) => this._thumb(p));
    return photos.length === 4 ? photos : photos.slice(0, 1);
  }

  // Waits `seconds`, showing them; true when it is time for the photo, false when cancelled.
  _countdown(seconds, hint) {
    return new Promise((resolve) => {
      const end = performance.now() + seconds * 1000;
      const tick = () => {
        if (this.state !== "capturing") { done(false); return; }
        const left = Math.ceil((end - performance.now()) / 1000);
        if (left <= 0) { done(true); return; }
        this._overlay(`${left}${hint ? `<br><small>${hint}</small>` : ""}`);
      };
      const timer = setInterval(tick, 100);
      const done = (ok) => { clearInterval(timer); this.skip = null; this._overlay(""); resolve(ok); };
      this.skip = () => done(this.state === "capturing");
      tick();
    });
  }

  // The middle square of the camera picture (the dashed frame), at most 1024 pixels.
  _shot() {
    const video = $("scan-cam");
    const side = Math.min(video.videoWidth, video.videoHeight);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = Math.min(side, 1024);
    canvas.getContext("2d").drawImage(video, (video.videoWidth - side) / 2, (video.videoHeight - side) / 2,
      side, side, 0, 0, canvas.width, canvas.height);
    return canvas;
  }

  // How sharp the picture is now: the spread of a Laplacian filter over a small grey copy.
  _sharpness(small) {
    const video = $("scan-cam");
    const side = Math.min(video.videoWidth, video.videoHeight);
    const ctx = small.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(video, (video.videoWidth - side) / 2, (video.videoHeight - side) / 2, side, side, 0, 0, small.width, small.height);
    const { data, width, height } = ctx.getImageData(0, 0, small.width, small.height);
    const grey = (i) => 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    let sum = 0, sum2 = 0, n = 0;
    for (let y = 1; y < height - 1; y += 1) {
      for (let x = 1; x < width - 1; x += 1) {
        const i = (y * width + x) * 4;
        const l = 4 * grey(i) - grey(i - 4) - grey(i + 4) - grey(i - width * 4) - grey(i + width * 4);
        sum += l; sum2 += l * l; n += 1;
      }
    }
    return sum2 / n - (sum / n) ** 2;
  }

  // A thumbs-up to the camera starts the scan (held for half a second, so it is meant).
  async _watchHands() {
    try {
      this.hands ||= await loadHandLandmarker();
    } catch { return; }                            // no hand tracking: the other ways still work
    const video = $("scan-cam");
    const look = () => {
      if (this.state === "closed") return;
      if (this.state === "ready" && video.readyState >= 2) {
        this.seeHand(this.hands.detectForVideo(video, performance.now()).landmarks?.[0]);
      }
      setTimeout(look, 120);
    };
    look();
  }

  // One look at the hand (21 landmarks, or nothing); tests call it with a synthetic one. A
  // thumbs-up held for half a second starts; the tracker missing it for a moment does not reset it.
  seeHand(landmarks, now = performance.now()) {
    if (this.state !== "ready" || !isThumbsUp(landmarks)) return;
    if (!this.thumbSince || now - this.thumbLast > 1000) this.thumbSince = now;   // slow trackers: a frame or two a second
    this.thumbLast = now;
    if (now - this.thumbSince > 500) { this.thumbSince = 0; this.trigger(); }
  }

  // ------------------------------------------------------------ to 3D, on the GPU

  async _upload(name, canvases) {
    this.state = "working";
    $("scan-go").disabled = true;
    const height = parseFloat($("scan-height").value) || 10;
    const n = canvases.length;
    const where = this.onGpu ? "on the GPU" : `(${this.health?.where || "Idol"})`;
    this._status(n > 1 ? `${n} photos taken. Idol is turning them into 3D ${where}…` : `Photo taken. Idol is turning it into 3D ${where}…`, "busy");
    this.onEvent("start", { name, views: n, backend: this.health?.backend, gpu: this.health?.gpu });
    const form = new FormData();
    for (const [k, canvas] of canvases.entries()) {
      form.append("image", await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92)), `view_${k}.jpg`);
    }
    form.append("name", name);
    form.append("height_cm", String(height));
    const poll = setInterval(() => this._poll(), 1000);
    try {
      const r = await fetch("./scan/scan", { method: "POST", body: form });
      const answer = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(answer.detail || `the scanner answered ${r.status}`);
      clearInterval(poll);
      this.onEvent("done", { ...answer, onGpu: this.onGpu });
      this.state = "ready";
      this.close();
      this.send(`create a ${answer.name}`);
    } catch (e) {
      clearInterval(poll);
      this.state = "ready";
      this._status(`The scan failed: ${e.message || e}`, "error");
      this.onEvent("failed", { name, message: String(e.message || e) });
    } finally {
      clearInterval(poll);
      $("scan-go").disabled = false;
    }
  }

  async _poll() {
    let p;
    try { p = await (await fetch("./scan/progress", { cache: "no-store" })).json(); } catch { return; }
    if (this.state !== "working" || p.state !== "running") return;
    const step = p.step === "idol"
      ? (p.views > 1 ? `Idol: photo ${p.view} of ${p.views}` : "Idol is making it 3D")
      : STEPS[p.step] || "Working";
    this._status(`${step}… ${Math.round(p.seconds || 0)} s`, "busy");
    this.onEvent("progress", { ...p, text: step, onGpu: this.onGpu });
  }

  // ------------------------------------------------------------ drawing

  _overlay(html, kind = "") {
    $("scan-overlay").innerHTML = html;
    $("scan-overlay").className = kind;
  }

  _flash() {
    const el = $("scan-flash");
    el.classList.remove("go");
    void el.offsetWidth;                           // restart the animation
    el.classList.add("go");
  }

  _thumb(canvas) {
    const img = document.createElement("img");
    img.src = canvas.toDataURL("image/jpeg", 0.6);
    img.alt = `photo ${$("scan-thumbs").children.length + 1}`;
    $("scan-thumbs").appendChild(img);
  }

  _status(text, kind = "") {
    $("scan-status").textContent = text;
    $("scan-status").className = kind;
  }
}
