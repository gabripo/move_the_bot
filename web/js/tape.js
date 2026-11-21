// Records the demo from inside the page (recording mode): Chrome captures this tab, cropped to one
// element (the robot's view and the command bar), so the cue column beside it stays out of the
// video. Start, pause and stop; the video is saved to the Downloads folder when it stops.
//
// Sound: your microphone (what you say) mixed with the tab's own sound, in one track.
// Codecs: H.264 video and AAC sound in MP4, what iMovie and QuickTime edit. Chrome's recorder
// writes a variable frame rate, which editors may drift on: `./record-demo.sh imovie` turns a
// recording into a constant 30 fps .mov for iMovie (see docs/development.md).
//
// Chrome asks once per recording which tab to share: choose this one ("Share this tab"), and keep
// "Also share tab audio" on.

// avc1 (parameter sets in the header) is what iMovie reads best: the recorder starts only once the
// crop has settled, so the size does not change after the first frame. avc3 is the fallback.
const TYPES = [
  "video/mp4;codecs=avc1.640028,mp4a.40.2", "video/mp4;codecs=avc1.4d0028,mp4a.40.2",
  "video/mp4;codecs=avc3.640028,mp4a.40.2", "video/mp4;codecs=avc1.640028", "video/mp4",
  "video/webm;codecs=vp9,opus", "video/webm",
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class Tape {
  constructor({ element, onState }) {
    this.element = element;            // what is recorded
    this.onState = onState;            // (state, info) => {}: "idle" | "starting" | "recording" | "paused" | "saved" | "error"
    this.state = "idle";
    this.recorder = null;
    this.stream = null;
    this.mic = null;
    this.audio = null;                 // the AudioContext mixing the sound
    this.meter = null;                 // an AnalyserNode on the microphone
    this.chunks = [];
    this.elapsed = 0;                  // ms recorded, pauses excluded
    this.since = 0;
    this.cropped = false;
    this.sound = "";                   // what the sound track holds, for the cues
  }

  get seconds() {
    return (this.elapsed + (this.state === "recording" ? performance.now() - this.since : 0)) / 1000;
  }

  // How loud the microphone is now, 0..1 (to see that it hears you).
  get level() {
    if (!this.meter) return 0;
    const data = new Float32Array(this.meter.fftSize);
    this.meter.getFloatTimeDomainData(data);
    let sum = 0;
    for (const v of data) sum += v * v;
    return Math.min(1, Math.sqrt(sum / data.length) * 6);
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
        video: { frameRate: 30 },
        audio: { suppressLocalAudioPlayback: false },      // the tab's sound, still heard while recording
        preferCurrentTab: true, selfBrowserSurface: "include", surfaceSwitching: "exclude",
        monitorTypeSurfaces: "exclude", systemAudio: "exclude",
      });
      const [track] = this.stream.getVideoTracks();
      track.addEventListener("ended", () => this.stop());   // Chrome's "Stop sharing" button
      // Only the recorded element, not the cue column (Region Capture, Chrome 104+). Fails when
      // another tab was chosen: then the whole choice is recorded, and the cues say so.
      this.cropped = false;
      if (window.CropTarget && track.cropTo) {
        try { await track.cropTo(await CropTarget.fromElement(this.element)); this.cropped = true; } catch { /* not this tab */ }
      }
      await this._settled(track);
      const sound = await this._sound();
      const tracks = [track, ...sound];
      const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t)) || "";
      this.recorder = new MediaRecorder(new MediaStream(tracks), {
        mimeType, videoBitsPerSecond: 16_000_000, audioBitsPerSecond: 192_000,
      });
      this.chunks = [];
      this.recorder.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
      this.recorder.onstop = () => this._save(mimeType);
      this.recorder.onerror = (e) => this._set("error", { message: e.error?.message || "the recorder stopped" });
      this.recorder.start(1000);
      this.elapsed = 0;
      this.since = performance.now();
      this._set("recording");
    } catch (e) {
      this._release();
      this._set(e && e.name === "NotAllowedError" ? "idle" : "error", { message: (e && (e.message || e.name)) || String(e) });
    }
  }

  // Waits until the cropped picture keeps the same size (the crop applies a frame or two late).
  async _settled(track) {
    let last = "";
    for (let i = 0; i < 20; i++) {
      await sleep(100);
      const { width, height } = track.getSettings();
      const now = `${width}x${height}`;
      if (now === last && width) return;
      last = now;
    }
  }

  // The microphone and the tab's sound, mixed into one track ([] when there is neither).
  async _sound() {
    const tab = this.stream.getAudioTracks();
    try {
      this.mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch { this.mic = null; }                        // no microphone allowed: the tab's sound only
    const sources = [...(this.mic ? this.mic.getAudioTracks() : []), ...tab];
    this.sound = [this.mic && "your voice", tab.length && "the tab's sound"].filter(Boolean).join(" + ") || "no sound";
    if (!sources.length) return [];
    this.audio = new AudioContext({ sampleRate: 48000 });
    const mix = this.audio.createMediaStreamDestination();
    for (const t of sources) this.audio.createMediaStreamSource(new MediaStream([t])).connect(mix);
    if (this.mic) {
      this.meter = this.audio.createAnalyser();
      this.meter.fftSize = 1024;
      this.audio.createMediaStreamSource(this.mic).connect(this.meter);
    }
    return mix.stream.getAudioTracks();
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
    const sound = this.sound;
    this._release();
    this._set("saved", { name, seconds, megabytes: blob.size / 1e6, sound, codec: mimeType });
  }

  _release() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.mic?.getTracks().forEach((t) => t.stop());
    this.audio?.close().catch(() => {});
    this.stream = this.mic = this.audio = this.meter = null;
    this.recorder = null;
    this.chunks = [];
  }

  _set(state, info = {}) {
    this.state = state;
    this.onState?.(state, { ...info, cropped: this.cropped, sound: info.sound || this.sound });
  }
}
