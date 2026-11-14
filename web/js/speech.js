// Voice input. Two ways to turn speech into text:
//   browser  the browser's built-in recognition (Chrome, Edge, Safari): instant, uses the
//            browser vendor's speech service
//   local    record in the browser, transcribe with the Whisper container of this project:
//            nothing leaves the computer (needs the `stt` service)

export class Speech {
  constructor({ onText, onState, onError }) {
    this.onText = onText;
    this.onState = onState;       // "idle" | "listening" | "transcribing"
    this.onError = onError;
    this.listening = false;
    this.mode = "browser";
    this.Recognition = window.SpeechRecognition || window.webkitSpeechRecognition || null;
  }

  get browserSupported() { return !!this.Recognition; }

  setMode(mode) {
    if (this.listening) this.stop();
    this.mode = mode;
  }

  toggle() { return this.listening ? this.stop() : this.start(); }

  async start() {
    if (this.listening) return;
    if (this.mode === "browser" && this.Recognition) return this._startBrowser();
    return this._startLocal();
  }

  stop() {
    if (this.recognition) { this.recognition.onend = null; this.recognition.stop(); this.recognition = null; }
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    if (this.stream) { this.stream.getTracks().forEach((t) => t.stop()); this.stream = null; }
    this.listening = false;
    if (!this.transcribing) this.onState("idle");
  }

  _startBrowser() {
    const r = new this.Recognition();
    r.continuous = true;
    r.interimResults = false;
    r.lang = "en-US";
    r.onresult = (event) => {
      const text = event.results[event.results.length - 1][0].transcript.trim();
      if (text) this.onText(text);
    };
    r.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") return;
      this.onError(event.error === "not-allowed"
        ? "The microphone is blocked: allow it in the browser's address bar."
        : `Speech recognition failed (${event.error}). You can type instead.`);
      this.stop();
    };
    r.onend = () => { if (this.listening) { try { r.start(); } catch { this.stop(); } } };
    this.recognition = r;
    r.start();
    this.listening = true;
    this.onState("listening");
  }

  async _startLocal() {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      this.onError("The microphone is blocked: allow it in the browser's address bar.");
      return;
    }
    const chunks = [];
    const type = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
    this.recorder = new MediaRecorder(this.stream, type ? { mimeType: type } : undefined);
    this.recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
    this.recorder.onstop = () => this._transcribe(new Blob(chunks, { type: type || "audio/webm" }));
    this.recorder.start();
    this.listening = true;
    this.onState("listening");
  }

  async _transcribe(blob) {
    if (!blob.size) return;
    this.transcribing = true;
    this.onState("transcribing");
    try {
      const form = new FormData();
      form.append("audio", blob, "command.webm");
      const response = await fetch("./stt/transcribe", { method: "POST", body: form });
      if (!response.ok) throw new Error(`speech service answered ${response.status}`);
      const data = await response.json();
      if (data.text) this.onText(data.text.trim());
    } catch (e) {
      this.onError(`Local speech recognition is not available (${e.message}). Start it with ./run.sh --voice, or type.`);
    }
    this.transcribing = false;
    this.onState("idle");
  }
}
