// The object scanner (optional, ./run.sh --scan): show an object to the webcam, give it a name
// and its height, and it becomes an object on the table. The photo goes to the scan service
// (docker/scan_server.py), where Idol turns it into 3D; then "create a <name>" places it.
// The Scan button only appears when the scan service answers.

import { openCamera } from "./camera.js";

const $ = (id) => document.getElementById(id);

export class Scanner {
  constructor({ send, onEvent }) {
    this.send = send;
    this.onEvent = onEvent || (() => {});
    this.stream = null;
    this.where = "";
    $("btn-scan").addEventListener("click", () => this.open());
    $("scan-cancel").addEventListener("click", () => this.close());
    $("scan-form").addEventListener("submit", (e) => { e.preventDefault(); this.scan(); });
    this._check();
  }

  async _check() {
    try {
      const r = await fetch("./scan/health", { cache: "no-store" });
      const health = r.ok ? await r.json() : null;
      if (health && health.ok) {
        this.where = health.where || "";
        $("btn-scan").hidden = false;
        $("btn-scan").title = `Turn an object you show to the webcam into a 3D object (Idol, ${this.where})`;
      }
    } catch { /* no scanner: the button stays hidden */ }
  }

  async open() {
    $("scan-panel").hidden = false;
    this._status("Hold the object inside the square, on a plain background.");
    $("scan-name").focus();
    try {
      this.stream = await openCamera({ width: { ideal: 1280 }, height: { ideal: 720 } });
      $("scan-cam").srcObject = this.stream;
    } catch (e) {
      this._status(e && e.name === "NotAllowedError" ? "The camera is blocked: allow it, then try again."
        : `The camera did not start: ${(e && e.message) || e}`, "error");
    }
  }

  close() {
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
    $("scan-cam").srcObject = null;
    $("scan-panel").hidden = true;
  }

  // The middle square of the camera picture, as a JPEG.
  _photo() {
    const video = $("scan-cam");
    const side = Math.min(video.videoWidth, video.videoHeight);
    if (!side) return Promise.resolve(null);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = Math.min(side, 1024);
    canvas.getContext("2d").drawImage(video, (video.videoWidth - side) / 2, (video.videoHeight - side) / 2,
      side, side, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
  }

  async scan() {
    const name = $("scan-name").value.trim();
    const height = parseFloat($("scan-height").value) || 10;
    const photo = await this._photo();
    if (!name || !photo) {
      this._status(name ? "No picture from the camera yet." : "Give it a name first.", "error");
      return;
    }
    $("scan-go").disabled = true;
    this._status("Photo taken. Idol is turning it into 3D (about 30 s)…", "busy");
    this.onEvent("start", { name });
    const form = new FormData();
    form.append("image", photo, "scan.jpg");
    form.append("name", name);
    form.append("height_cm", String(height));
    try {
      const r = await fetch("./scan/scan", { method: "POST", body: form });
      const answer = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(answer.detail || `the scanner answered ${r.status}`);
      this.onEvent("done", answer);
      this.close();
      this.send(`create a ${answer.name}`);
    } catch (e) {
      this._status(`The scan failed: ${e.message || e}`, "error");
      this.onEvent("failed", { name, message: String(e.message || e) });
    } finally {
      $("scan-go").disabled = false;
    }
  }

  _status(text, kind = "") {
    $("scan-status").textContent = text;
    $("scan-status").className = kind;
  }
}
