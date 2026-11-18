// Records the demo from inside the page (recording mode): Chrome captures this tab, cropped to one
// element (the robot's view and the command bar), so the cue column beside it stays out of the
// video. Start, pause and stop; the video is saved to the Downloads folder when it stops.
//
// Chrome asks once per recording which tab to share: choose this one ("Share this tab").

// avc3: the crop may change the size once at the start, which avc1 does not allow.
const TYPES = ["video/mp4;codecs=avc3.640028", "video/mp4;codecs=avc1.640028", "video/mp4", "video/webm;codecs=vp9", "video/webm"];

export class Tape {
  constructor({ element, onState }) {
    this.element = element;            // what is recorded
    this.onState = onState;            // (state, info) => {}: "idle" | "starting" | "recording" | "paused" | "saved" | "error"
    this.state = "idle";
    this.recorder = null;
    this.stream = null;
    this.chunks = [];
    this.elapsed = 0;                  // ms recorded, pauses excluded
    this.since = 0;
    this.cropped = false;
  }

  get seconds() {
    return (this.elapsed + (this.state === "recording" ? performance.now() - this.since : 0)) / 1000;
  }

  async toggle() {
    if (this.state === "idle" || this.state === "saved" || this.state === "error") return this.start();
    if (this.state === "recording" || this.state === "paused") return this.stop();
  }

  pause() {
    if (this.state === "recording") {
      this.recorder.pause();
      this.elapsed += performance.now() - this.since;
      this._set("paused");
    } else if (this.state === "paused") {
      this.recorder.resume();
      this.since = performance.now();
      this._set("recording");
    }
  }

  async start() {
    this._set("starting");
    try {
      if (!navigator.mediaDevices?.getDisplayMedia) throw new Error("This browser cannot record a tab: use Chrome");
      this.stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 30 }, audio: false,
        preferCurrentTab: true, selfBrowserSurface: "include", surfaceSwitching: "exclude",
        monitorTypeSurfaces: "exclude",
      });
      const [track] = this.stream.getVideoTracks();
      track.addEventListener("ended", () => this.stop());   // Chrome's "Stop sharing" button
      // Only the recorded element, not the cue column (Region Capture, Chrome 104+). Fails when
      // another tab was chosen: then the whole choice is recorded, and the cues say so.
      this.cropped = false;
      if (window.CropTarget && track.cropTo) {
        try { await track.cropTo(await CropTarget.fromElement(this.element)); this.cropped = true; } catch { /* not this tab */ }
      }
      const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t)) || "";
      this.recorder = new MediaRecorder(this.stream, { mimeType, videoBitsPerSecond: 16_000_000 });
      this.chunks = [];
      this.recorder.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
      this.recorder.onstop = () => this._save(mimeType);
      this.recorder.start(1000);
      this.elapsed = 0;
      this.since = performance.now();
      this._set("recording");
    } catch (e) {
      this._release();
      this._set(e && e.name === "NotAllowedError" ? "idle" : "error", { message: (e && (e.message || e.name)) || String(e) });
    }
  }

  stop() {
    if (!this.recorder || this.recorder.state === "inactive") return;
    if (this.state === "recording") this.elapsed += performance.now() - this.since;
    this.recorder.stop();               // then onstop saves it
  }

  _save(mimeType) {
    const ext = mimeType.startsWith("video/mp4") ? "mp4" : "webm";
    const blob = new Blob(this.chunks, { type: mimeType || "video/webm" });
    const d = new Date(), two = (n) => String(n).padStart(2, "0");
    const stamp = `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}_${two(d.getHours())}-${two(d.getMinutes())}-${two(d.getSeconds())}`;
    const name = `move_the_bot-${stamp}.${ext}`;
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60_000);
    const seconds = this.elapsed / 1000;
    this._release();
    this._set("saved", { name, seconds, megabytes: blob.size / 1e6 });
  }

  _release() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.recorder = null;
    this.chunks = [];
  }

  _set(state, info = {}) {
    this.state = state;
    this.onState?.(state, { ...info, cropped: this.cropped });
  }
}
