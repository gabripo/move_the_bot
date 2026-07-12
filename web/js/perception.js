class PerceptionModule {
  constructor(bridge) {
    this.bridge = bridge;
    this.video = document.getElementById("camera-feed");
    this.cameraActive = false;
    this.micActive = false;
    this.handLandmarker = null;
    this.recognition = null;
    this.detectId = null;
    this._mediaRecorder = null;
    this._audioChunks = null;
    this._isTranscribing = false;
  }

  async startCamera() {
    if (this.cameraActive) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      this.video.srcObject = stream;
      await this.video.play();
      this.cameraActive = true;
      this.loadHandLandmarker();
    } catch (e) {
      console.error("Camera error:", e);
      alert("Camera access denied. Please grant camera permission.");
    }
  }

  stopCamera() {
    if (this.video.srcObject) {
      this.video.srcObject.getTracks().forEach((t) => t.stop());
    }
    this.cameraActive = false;
    if (this.detectId) {
      cancelAnimationFrame(this.detectId);
      this.detectId = null;
    }
  }

  async loadHandLandmarker() {
    try {
      const vision = await FilesetResolver.forVisionTasks(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm/"
      );
      this.handLandmarker = await HandLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath:
            "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
        },
        runningMode: "VIDEO",
        numHands: 1,
      });
      this.detectLoop();
    } catch (e) {
      console.error("MediaPipe load error:", e);
    }
  }

  detectLoop() {
    const detect = async () => {
      if (
        this.handLandmarker &&
        this.video.readyState >= 2 &&
        this.cameraActive
      ) {
        const result = this.handLandmarker.detectForVideo(
          this.video,
          performance.now()
        );
        if (result.landmarks && result.landmarks.length > 0) {
          const idx = result.landmarks[0][8];
          const thmb = result.landmarks[0][4];
          const mid = {
            x: (idx.x + thmb.x) / 2,
            y: (idx.y + thmb.y) / 2,
            z: (idx.z + thmb.z) / 2,
          };
          const wx = (mid.x - 0.5) * 0.6;
          const wy = 0.5 - mid.y * 0.5;
          const wz = (1.0 - mid.z) * 0.4;
          this.bridge.publishPoint("/spatial_coords", wx, wy, wz);
          document.getElementById("coords").innerHTML =
            `<span class="stat-label">Hand:</span> ` +
            `<span class="stat-value">(${wx.toFixed(3)}, ${wy.toFixed(3)}, ${wz.toFixed(3)})</span>`;
        }
      }
      this.detectId = requestAnimationFrame(detect);
    };
    detect();
  }

  // ---- Mic / Speech Recognition ----

  toggleMic() {
    if (this.micActive || this._isTranscribing) {
      this.stopMic();
    } else {
      this.startMic();
    }
  }

  async startMic() {
    if (this.micActive || this._isTranscribing) return;

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (SR) {
      this._startNative(SR);
    } else {
      this._startServerSTT();
    }
  }

  _startNative(SR) {
    this.recognition = new SR();
    this.recognition.continuous = true;
    this.recognition.interimResults = false;
    this.recognition.lang = "en-US";
    this.recognition.onresult = (event) => {
      const text = event.results[event.results.length - 1][0].transcript;
      this._publishResult(text);
    };
    this.recognition.onerror = (e) => {
      console.error("Speech error:", e.error);
      if (e.error !== "aborted" && e.error !== "no-speech") {
        alert(`Speech error: ${e.error}. Try typing instead.`);
      }
      this.stopMic();
    };
    this.recognition.start();
    this.micActive = true;
    this._setMicUI(true, "Stop Mic");
  }

  // ---- Server-side STT (Firefox fallback) ----

  async _startServerSTT() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      alert("Microphone access denied. Please grant permission.");
      return;
    }

    this._audioChunks = [];
    this._mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
    this._mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) this._audioChunks.push(e.data);
    };
    this._mediaRecorder.onstop = () => this._sendToServer();
    this._mediaRecorder.start();
    this._micStream = stream;
    this.micActive = true;
    this._setMicUI(true, "Stop Mic");
  }

  async _sendToServer() {
    if (!this._audioChunks || this._audioChunks.length === 0) return;

    this._isTranscribing = true;
    this._setMicUI(false, "Transcribing\u2026");

    try {
      const blob = new Blob(this._audioChunks, { type: "audio/webm" });
      const formData = new FormData();
      formData.append("audio", blob, "recording.webm");

      const res = await fetch("/stt/transcribe", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(`Server error ${res.status}: ${errText}`);
      }

      const data = await res.json();
      if (data && data.text) {
        this._publishResult(data.text);
      }
    } catch (e) {
      console.error("Server STT error:", e);
      alert(`Transcription failed: ${e.message}. Use text input.`);
    }

    this._isTranscribing = false;
    this._setMicUI(false, "Start Mic");
  }

  _publishResult(text) {
    this.bridge.publishString("/voice_commands", text);
    document.getElementById("voice").innerHTML =
      `<span class="stat-label">Voice:</span> <span class="stat-value">"${text}"</span>`;
    this.bridge.addLogEntry(`Recognized: "${text}"`);
  }

  stopMic() {
    if (this.recognition) {
      this.recognition.stop();
      this.recognition = null;
    }
    if (this._mediaRecorder && this._mediaRecorder.state !== "inactive") {
      this._mediaRecorder.stop();
      this._mediaRecorder = null;
    }
    if (this._micStream) {
      this._cleanupStream(this._micStream);
      this._micStream = null;
    }
    this.micActive = false;
    this._setMicUI(false, "Start Mic");
  }

  _setMicUI(active, text) {
    const btn = document.getElementById("btn-mic");
    btn.textContent = text;
    btn.classList.toggle("active", active);
  }

  _cleanupStream(stream) {
    if (stream) stream.getTracks().forEach((t) => t.stop());
  }
}
