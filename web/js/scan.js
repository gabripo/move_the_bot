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
// In recording mode (quickStart) Space and a thumbs-up also start a scan with the panel closed:
// the thumbs-up is then watched through the webcam bubble, and the last name is used again.
//
// A scan that went wrong is forgotten with the ✕ next to it in "Your scans", or by saying (or
// typing) "delete the mug scan" / "forget the scanned mug": the object is taken off the table, and
// "create a mug" then draws it as before the scan. Lists of scans follow the "mtb-scans" event.

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
  constructor({ send, onEvent, quickStart, pcName = "my gaming PC" }) {
    this.pcName = pcName;                              // where Idol runs, when it is on a GPU PC
    this.send = send;
    this.onEvent = onEvent || (() => {});
    this.quickStart = quickStart || (() => false);     // Space / 👍 with the panel closed
    try { this.lastName = localStorage.getItem("mtb.scan.name") || ""; } catch { this.lastName = ""; }
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
      if (e.key !== " ") return;
      // In the name box a tap types a space ("red mug"); holding Space starts the scan instead of
      // filling the box with spaces (which scrolls the name out of sight). In the height box, Space starts.
      if (e.target === $("scan-name") || e.target === $("scan-height")) {
        if (e.target === $("scan-height") || e.repeat) {
          e.preventDefault();
          if (this.state === "ready" && $("scan-name").value.trim() && !this.starting) this.trigger();
        }
        return;
      }
      if (e.repeat || e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (this.state === "closed" && !(this.quickStart() && !$("btn-scan").hidden)) return;
      e.preventDefault();
      if (e.target.tagName === "BUTTON") e.target.blur();
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
    if (first) this._changed();
    // Idol's public demo takes one photo (its free quota is small): no several-photo modes.
    const many = health.backend !== "demo";
    for (const id of ["scan-mode-sides", "scan-mode-video"]) $(id).disabled = !many;
    if (first || !many) $(many ? "scan-mode-sides" : "scan-mode-photo").checked = true;
  }

  // ------------------------------------------------------------ open, close, start

  async open({ name = "", height = null, start = false } = {}) {
    if (this.state === "working") return;
    if (name) $("scan-name").value = name;
    else if (!$("scan-name").value && this.lastName) $("scan-name").value = this.lastName;
    if (height) $("scan-height").value = String(height);
    if (this.state === "closed") {
      this.state = "ready";
      $("scan-panel").hidden = false;
      $("scan-thumbs").replaceChildren();
      this._overlay("");
      this._status("Hold the object inside the square, on a plain background. Start: the button, Space, a 👍 or say “scan …”.");
      if (!$("scan-name").value) $("scan-name").focus();     // else Space would type into it
      else if (document.activeElement === $("scan-name")) $("scan-name").blur();
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
    this.closedAt = performance.now();
    this.skip?.();
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
    $("scan-cam").srcObject = null;
    $("scan-panel").hidden = true;
  }

  // The button, Space, "next", a thumbs-up: start, or take the next photo now.
  trigger() {
    if (this.state === "closed") this.open({ start: !!this.lastName });   // recording mode: Space / 👍
    else if (this.state === "ready" && !this.starting) this._run();
    else if (this.state === "capturing") this.skip?.();
  }

  // ------------------------------------------------------------ scans made so far

  async scans() {
    try {
      const r = await fetch("./scan/scans", { cache: "no-store" });
      return r.ok ? await r.json() : [];
    } catch { return []; }
  }

  // Forget a scan; the object leaves the table, so the next "create" draws it the old way.
  async forget(name) {
    let answer;
    try {
      const r = await fetch(`./scan/scans/${encodeURIComponent(name)}`, { method: "DELETE" });
      answer = await r.json();
      if (!r.ok) throw new Error(answer.detail || r.statusText);
    } catch (e) {
      this.onEvent("forget-failed", { name, message: `Could not forget the scan of ${name}: ${e.message || e}` });
      return false;
    }
    if ((window.mtb?.objects || []).some((o) => o.name === answer.removed)) this.send(`remove the ${answer.removed}`);
    this.onEvent("forgot", { name: answer.removed });
    this._changed();
    return true;
  }

  _changed() {
    window.dispatchEvent(new Event("mtb-scans"));
    this._list();
  }

  async _list() {
    const list = $("scan-list");
    const scans = await this.scans();
    list.replaceChildren(...scans.map((s) => {
      const li = document.createElement("li");
      const x = Object.assign(document.createElement("button"), { type: "button", textContent: "✕", title: `Forget the scan of ${s.name}` });
      x.addEventListener("click", () => this.forget(s.name));
      li.append(s.name, x);
      return li;
    }));
    $("scan-list-box").hidden = !scans.length;
  }

  // Words from the command box or the microphone. True when they were for the scanner.
  command(text) {
    const t = text.trim().toLowerCase().replace(/[.!?]+$/, "");
    // "delete the mug scan", "forget the scanned mug", "remove the scan of my mug": only with
    // the word scan, since "remove the mug" takes the mug off the table.
    const f = t.match(/^(?:please\s+)?(?:delete|forget|remove|discard|throw away)\s+(?:the\s+|my\s+)?(?:scan(?:ned)?\s+(?:of\s+)?)?(?:the\s+|my\s+|a\s+)?(.+?)(\s+scan)?$/);
    if (f && !$("btn-scan").hidden && (f[2] || /\bscan/.test(t.slice(0, t.length - f[1].length)))) {
      this.forget(f[1].trim());
      return true;
    }
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
    if (!name) { this._status("Give it a name first, then Enter.", "error"); $("scan-name").focus(); return; }
    this.lastName = name;
    try { localStorage.setItem("mtb.scan.name", name); } catch { /* private mode */ }
    if (document.activeElement === $("scan-name") || document.activeElement === $("scan-height")) document.activeElement.blur();
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

  // Recording mode: a thumbs-up to the webcam bubble starts a scan with the panel closed.
  async watchIdle(video) {
    try {
      this.hands ||= await loadHandLandmarker();
    } catch { return; }
    const look = () => {
      if (this.state === "closed" && this.quickStart() && !$("btn-scan").hidden && video.readyState >= 2 && video.videoWidth) {
        try { this.seeHand(this.hands.detectForVideo(video, performance.now()).landmarks?.[0]); } catch { /* a frame it could not read */ }
      }
      setTimeout(look, 150);
    };
    look();
  }

  // One look at the hand (21 landmarks, or nothing); tests call it with a synthetic one. A
  // thumbs-up held for half a second starts; the tracker missing it for a moment does not reset it.
  seeHand(landmarks, now = performance.now()) {
    // Closed: only in recording mode, and not just after a scan (the hand may still be up).
    if (this.state !== "ready" && !(this.state === "closed" && this.quickStart() && now - (this.closedAt || -1e9) > 5000)) return;
    if (!isThumbsUp(landmarks)) return;
    if (!this.thumbSince || now - this.thumbLast > 1000) {           // slow trackers: a frame or two a second
      this.thumbSince = now;
      if (this.state === "ready") this._status("👍 seen: hold it…", "busy");
    }
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
    this._cardStart(name, canvases);
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
      this._cardEnd(true, `“${answer.name}” is ready`, `3D from ${n > 1 ? `${n} photos` : "one photo"} in ${Math.round(answer.seconds)} s`
        + ` · ${(answer.points || 0).toLocaleString()} points`);
      this._changed();
      this.state = "ready";
      this.close();
      this.send(`create a ${answer.name}`);
    } catch (e) {
      clearInterval(poll);
      this.state = "ready";
      this._status(`The scan failed: ${e.message || e}`, "error");
      this.onEvent("failed", { name, message: String(e.message || e) });
      this._cardEnd(false, "The scan failed", String(e.message || e));
      this.close();                                  // Space, 👍 or "scan …" try again
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
    this._cardProgress(p);
  }

  // ------------------------------------------------------------ the card while Idol works

  // The photos are taken: back to the 3D view, with a card saying what Idol does, and where.
  _cardStart(name, canvases) {
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());   // the camera is done
    this.stream = null;
    $("scan-cam").srcObject = null;
    $("scan-panel").hidden = true;
    const n = canvases.length, remote = this.health?.backend === "remote";
    const gpu = this.health?.gpu ? ` · ${this.health.gpu}` : "";
    $("idol-title").textContent = `Idol is building “${name}” in 3D`;
    $("idol-where").textContent = remote ? `on ${this.pcName}'s GPU${gpu}`
      : this.health?.backend === "local" ? `on this computer's GPU${gpu}` : (this.health?.where || "");
    $("idol-photos").replaceChildren(...canvases.map((c, k) => Object.assign(document.createElement("img"),
      { src: c.toDataURL("image/jpeg", 0.7), alt: `photo ${k + 1}` })));
    const steps = [];
    if (remote) steps.push(["sending", `Sending ${n > 1 ? `the ${n} photos` : "the photo"} to ${this.pcName}`]);
    if (this.onGpu) steps.push(["loading", "Loading Idol and SAM 2 into the GPU's memory"]);
    steps.push(["idol", n > 1 ? "Each photo: cut out, → 3D Gaussians" : "The photo: cut out, → 3D Gaussians"]);
    if (n > 1) steps.push(["fusing", "Finding each photo's turn, merging the sides"]);
    steps.push(["model", "The 3D model, at the object's real size"]);
    $("idol-steps").replaceChildren(...steps.map(([key, text]) => {
      const li = document.createElement("li");
      li.dataset.key = key;
      li.append(text, document.createElement("small"));
      return li;
    }));
    const gaussians = (this.health?.gaussians || 262144).toLocaleString();
    this.notes = [
      `Idol, an open image-to-3D model by Sperid Labs, turns each photo into ${gaussians} 3D Gaussians: small coloured, see-through blobs.`,
      "First SAM 2, Meta's segment-anything model, cuts the object out of each photo, so nothing behind it becomes 3D.",
      n > 1 ? "From one photo it has to invent the hidden sides; the other photos show what they really look like." : "From one photo it invents the sides the camera did not see.",
      `It runs on ${remote ? this.pcName : "this computer"}'s GPU. The language model steps aside meanwhile, to give it the video memory.`,
      n > 1 ? "Then the results are turned until the surfaces they share match, and merged into one object." : "Then the blobs become points with the object's real height.",
      "The robot will grasp the result as a box of its real size.",
    ];
    this.card = { n, started: performance.now(), key: "", keyStarted: performance.now(), times: {}, note: 0, noteAt: 0,
      view: 0, viewStarted: 0, viewTimes: [] };
    clearTimeout(this.cardHide);
    $("idol-card").className = "";
    $("idol-card").hidden = false;
    $("idol-bar").firstElementChild.style.width = "2%";
    this._cardNote();
    clearInterval(this.cardTimer);
    this.cardTimer = setInterval(() => {
      const s = (performance.now() - this.card.started) / 1000;
      $("idol-time").textContent = `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
      if (Math.floor(s) % 7 === 0 && Math.floor(s) !== this.card.noteAt) { this.card.noteAt = Math.floor(s); this._cardNote(); }
      this._cardDraw();
    }, 250);
    this._cardProgress({ step: remote ? "sending" : this.onGpu ? "loading" : "idol", view: 1, views: n });
  }

  _cardNote() {
    const note = $("idol-note");
    note.style.opacity = 0;
    setTimeout(() => { note.textContent = this.notes[this.card.note++ % this.notes.length]; note.style.opacity = 1; }, 300);
  }

  _cardProgress(p) {
    if (!this.card) return;
    // What Idol was shown: each photo with only the object left, as soon as it is cut out.
    (p.cutouts || []).forEach((src, k) => {
      const img = $("idol-photos").children[k];
      if (src && img && img.src !== src) { img.src = src; img.classList.add("cut"); img.title = "What Idol sees: only the object"; }
    });
    const now = performance.now();
    if (p.step === "idol") {                         // one row for all photos; each photo timed
      const view = Math.min(p.view || 1, this.card.n);
      if (view !== this.card.view) {
        if (this.card.view) this.card.viewTimes.push((now - this.card.viewStarted) / 1000);
        this.card.view = view;
        this.card.viewStarted = now - 1000 * (p.view_seconds || 0);
      }
    }
    const key = p.step;
    if (!$("idol-steps").querySelector(`[data-key="${key}"]`) || key === this.card.key) return;
    if (this.card.key) this.card.times[this.card.key] = (now - this.card.keyStarted) / 1000;
    this.card.key = key;
    this.card.keyStarted = now;
    this._cardDraw();
  }

  _cardDraw() {
    const items = [...$("idol-steps").children];
    const at = items.findIndex((li) => li.dataset.key === this.card.key);
    const c = this.card, now = performance.now();
    const t = c.viewTimes, perView = t.length ? t.reduce((a, b) => a + b, 0) / t.length : 45;
    const typical = { sending: 3, loading: 25, idol: perView * c.n, fusing: 15, model: 4 };
    let total = 0, done = 0;
    items.forEach((li, i) => {
      const key = li.dataset.key, expect = typical[key] || 5;
      li.className = i < at ? "done" : i === at ? "now" : "";
      const took = i < at ? c.times[key] : i === at ? (now - c.keyStarted) / 1000 : null;
      let label = took == null ? "" : `${Math.round(took)} s`;
      let fraction = took == null ? 0 : Math.min(took / expect, 0.95);
      if (key === "idol" && i === at && c.n > 1) {
        const inView = (now - c.viewStarted) / 1000;
        label = `photo ${c.view} of ${c.n} · ${Math.round(inView)} s`;
        fraction = (c.view - 1 + Math.min(inView / perView, 0.95)) / c.n;
      }
      li.lastElementChild.textContent = label;
      total += expect;
      if (i < at) done += expect;
      else if (i === at) done += fraction * expect;
    });
    $("idol-bar").firstElementChild.style.width = `${Math.max(2, Math.round((100 * done) / total))}%`;
    const view = c.key === "idol" ? c.view : ["fusing", "model"].includes(c.key) ? c.n + 1 : 0;
    [...$("idol-photos").children].forEach((img, k) => {
      img.classList.toggle("now", k + 1 === view);
      img.classList.toggle("done", k + 1 < view);
    });
  }

  _cardEnd(ok, title, detail) {
    clearInterval(this.cardTimer);
    if (!this.card) return;
    if (ok) {
      [...$("idol-steps").children].forEach((li) => { li.className = "done"; });
      $("idol-bar").firstElementChild.style.width = "100%";
      [...$("idol-photos").children].forEach((img) => { img.classList.remove("now"); img.classList.add("done"); });
    }
    $("idol-card").className = ok ? "done" : "failed";
    $("idol-title").textContent = title;
    $("idol-note").textContent = detail;
    $("idol-note").style.opacity = 1;
    this.card = null;
    clearTimeout(this.cardHide);
    this.cardHide = setTimeout(() => { $("idol-card").hidden = true; }, ok ? 2500 : 8000);
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
