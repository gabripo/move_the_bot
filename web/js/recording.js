// Recording mode: open the page with ?rec to record a demo that explains itself with the sound
// off. Big captions say what was asked and what happened; a live diagram lights up the part of
// the system that is working (the browser, the ROS 2 "brain", the language model on another
// computer, the arm); the webcam shows the person in a round bubble.
//
// Keys (when the command box is not focused), also listed, clickable, in a column beside the
// recorded area, with the script of the demo as a checklist; that column is never recorded:
//   V  start / stop the video (Chrome records this tab, cropped to the demo; saved to Downloads)
//   P  pause / resume the video
//   S  set the scene: clear the table and create the objects for the demo (not captioned)
//   R  ready for a take: clear captions, show the opening title, untick the script
//   E  show or hide the closing card          H  hand control on/off
//   M  speak a command                         Esc  stop the arm
//   /  type a command
//
// URL options: hook=…&hook2=… (opening title), setup=… (objects for S, ";" between commands),
// desk=0 (plain table instead of a desk), llmpc=… (where the language model runs),
// script=… (the script in the cue column, ";" between lines).

import { openCamera } from "./camera.js";
import { Tape } from "./tape.js";

const $ = (id) => document.getElementById(id);
const norm = (text) => text.toLowerCase().replace(/\s+/g, " ").trim();
const MOTION = new Set(["pick", "place", "move_to", "move_by", "home", "reset"]);
const SCRIPT = [
  "R · opening title, 2 s",
  "M · “I'm thirsty” (the LLM plans it)",
  "type “put the apple on the cube” (rules)",
  "H · steer with the hand, pinch to grab · H",
  "“create a ball here”",
  "👍 or “scan my mug” · 4 sides, a quarter turn each",
  "wait for the GPU PC (cut in the edit)",
  "“pick up the mug”",
  "E · end card, 3 s · V stops the video",
];
const ICONS = { voice: "🎤", text: "⌨️", hand: "✋", "voice+hand": "🎤✋", click: "🖱️", scan: "📷" };

export class Recording {
  constructor({ ros, viewer, params, actions }) {
    this.ros = ros;
    this.actions = actions;
    this.sources = new Map();         // command text -> how it was given
    this.quiet = new Set();           // setup commands: not captioned
    this.muted = false;
    this.teleop = false;
    this.settle = null;
    this.hookTimer = null;
    this.llmPc = params.get("llmpc") || "my gaming PC";
    this.setup = (params.get("setup")
      || "clear the table;create a mug on the right;create a red cube in front;create an apple on the left")
      .split(";").map((s) => s.trim()).filter(Boolean);

    document.body.classList.add("rec");
    $("rec").hidden = false;
    $("rec-hook-1").textContent = params.get("hook") || "I talk to a robot arm. It understands.";
    $("rec-hook-2").textContent = params.get("hook2") || "Voice, text or my hand · the AI runs on my own GPU";
    if (params.get("desk") !== "0") {
      viewer.setDesk(true);
      viewer.setView("desk");
    }

    // Keep the 3D view clear of the captions and the diagram.
    new ResizeObserver(() => {
      document.body.style.setProperty("--rec-h", `${$("rec-bottom").offsetHeight}px`);
    }).observe($("rec-bottom"));

    this._camera();
    $("rec-bubble").addEventListener("click", () => this._camera());
    ros.subscribe("/agent_log", "std_msgs/String", (msg) => {
      try { this._log(JSON.parse(msg.data)); } catch { /* not JSON: nothing to show */ }
    }, { queue: 100 });
    ros.subscribe("/skill/status", "std_msgs/String", (msg) => {
      try { this._status(JSON.parse(msg.data)); } catch { /* ignore */ }
    }, { queue: 50 });
    this.llmRest = "only when the rules don't understand";
    ros.subscribe("/agent/state", "std_msgs/String", (msg) => {
      try {
        const state = JSON.parse(msg.data);
        if (!state.model) return;
        this.llmRest = `${state.model.replace(/-instruct.*$/, "")} · only when needed`;
        if ($("flow-llm").className === "node llm") $("flow-llm-model").textContent = this.llmRest;
      } catch { /* ignore */ }
    }, { latched: true });
    window.addEventListener("keydown", (e) => this._key(e));
    this._cues(params);
    this.ready();
  }

  // The column beside the recorded area: the video's state, the keys (clickable) and the script.
  _cues(params) {
    $("rec-cues").hidden = false;
    for (const button of $("rec-keys").querySelectorAll("button")) {
      button.addEventListener("mousedown", (e) => e.preventDefault());   // keep the focus where it was (Space scans)
      button.addEventListener("click", () => this._do(button.dataset.key));
    }
    const lines = params.get("script") ? params.get("script").split(";").map((l) => l.trim()).filter(Boolean) : SCRIPT;
    for (const line of lines) {
      const li = document.createElement("li");
      li.textContent = line;
      li.addEventListener("click", () => li.classList.toggle("done"));
      $("rec-script").appendChild(li);
    }
    const show = (cls, title, note) => {
      $("tape-state").className = cls;
      $("tape-state").querySelector("b").textContent = title;
      $("tape-state").querySelector("span").textContent = note;
    };
    const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
    const crop = () => (this.tape.cropped ? "only the demo area" : "the whole tab: the cues are in it");
    let timer = null;
    this.tape = new Tape({
      element: $("app"),
      onState: (state, info) => {
        clearInterval(timer);
        if (state === "recording") {
          const tick = () => show("recording", `REC ${clock(this.tape.seconds)}`, `P pauses · V stops and saves · ${crop()}`);
          tick();
          timer = setInterval(tick, 250);
        } else if (state === "paused") {
          show("paused", `Paused ${clock(this.tape.seconds)}`, "P resumes · V stops and saves");
        } else if (state === "starting") {
          show("starting", "Starting…", "Chrome asks which tab: choose this one, then Share");
        } else if (state === "saved") {
          show("saved", `Saved · ${clock(info.seconds)}`, `${info.name} in Downloads (${info.megabytes.toFixed(1)} MB) · V records again`);
        } else if (state === "error") {
          show("error", "Could not record", `${info.message} · use ⌘⇧5 instead`);
        } else {
          show("idle", "Not recording", "V starts · Chrome asks which tab: this one");
        }
      },
    });
  }

  // The page tells us how a command was given, before sending it.
  source(text, how) { this.sources.set(norm(text), how); }

  setTeleop(on) {
    this.teleop = on;
    $("rec-bubble").classList.toggle("off", on);     // the hand-tracking preview takes its place
    if (on) {
      this._hideHook(1500);
      this._caption("✋ Hand control", "The gripper follows my hand · pinch to grab, open to let go");
      this._flow({ you: ["on", "✋ hand, tracked in the browser"],
        brain: ["on", "inverse kinematics, 15 times a second"],
        llm: ["skip", "not needed"], arm: ["on", "following the hand"] });
    } else {
      this._flow({});
      this._caption("", "");
    }
  }

  // The object scanner (scan.js): the webcam takes the photos, then Idol turns them into 3D.
  // When Idol runs on the GPU PC, that PC's box shows its progress, photo by photo.
  scan(state, info) {
    const photos = (n) => (n > 1 ? `${n} photos` : "one photo");
    const IDOL = "Idol · photos → 3D";
    if (state === "capture") {
      this._hideHook(1500);
      const how = info.mode === "video" ? "a short video, one slow turn" : info.shots > 1 ? "4 sides, a quarter turn each" : "one photo";
      this._caption(`📷 Scanning “${info.name}”`, `The webcam takes ${how}`);
      const now = info.mode === "video" ? `🎥 one turn${info.shot ? ` · side ${info.shot} of 4` : ""}`
        : info.shots > 1 ? `📷 photo ${info.shot} of ${info.shots}` : "📷 a photo";
      this._flow({ you: ["on", now] });
    } else if (state === "start") {
      this.scanSub = "";
      const gpu = ["remote", "local"].includes(info.backend);
      this._flow({ you: ["done", `📷 ${photos(info.views)}`], llm: gpu ? ["on", "receiving the photos…", IDOL] : ["skip", "not needed"] });
      this._sub(gpu ? `Idol, an open image-to-3D model, turns ${photos(info.views)} into 3D on ${this.llmPc}'s GPU…`
        : `Idol turns ${photos(info.views)} into 3D…`, gpu ? "llm" : "");
    } else if (state === "progress") {
      if (!info.onGpu) return;
      const what = info.step === "idol" && info.views > 1 ? `photo ${info.view} of ${info.views}` : info.text.toLowerCase();
      this._flow({ llm: ["on", `${what} · ${Math.round(info.seconds || 0)} s`, IDOL] }, true);
    } else if (state === "done") {
      this.scanSub = `3D from ${photos(info.views)} in ${info.seconds} s, made by Idol${info.onGpu ? ` on ${this.llmPc}'s GPU` : ""}`
        + ` (${info.points.toLocaleString()} points)`;
      this._sub(this.scanSub, info.onGpu ? "llm" : "");
      this._flow({ you: ["done", "📷 scanned"], ...(info.onGpu ? { llm: ["done", `${photos(info.views)} → 3D in ${Math.round(info.seconds)} s`, IDOL] } : {}) }, true);
    } else {
      this._sub(info.message, "error");
      this._flow({ you: ["done", "📷 scan failed"] });
    }
  }

  ready() {
    this._caption("", "");
    this._flow({});
    $("rec-end").hidden = true;
    clearTimeout(this.hookTimer);
    $("rec-hook").classList.remove("hide");
  }

  // ------------------------------------------------------------------ events

  _log(entry) {
    const text = entry.text || "";
    if (entry.role === "user") {
      const key = norm(text);
      if (this.quiet.has(key)) { this.quiet.delete(key); this.muted = true; return; }
      this.muted = false;
      if (key === "stop") { this._caption("🛑 “Stop”", "Stopped at once"); return; }
      let how = this.sources.get(key) || "text";
      if (this.teleop && how === "voice") how = "voice+hand";
      this.sources.delete(key);
      this._hideHook(2500);
      if (how === "scan") {           // the scanner places what it made: keep its result in view
        this._caption(`${ICONS.scan} “${text}”`, this.scanSub || "");
        this._flow({ you: ["done", "📷 scanned"] }, true);
        return;
      }
      this._caption(`${ICONS[how] || ""} “${text}”`, "");
      this._flow({ you: ["done", { voice: "🎤 voice", text: "⌨️ typed", "voice+hand": "🎤 voice + ✋ pointing", click: "🖱️ button" }[how] || "typed"] });
      return;
    }
    if (this.muted) return;
    if (entry.role === "info" && text.startsWith("Understood by the rules")) {
      this._flow({ brain: ["on", "rules: understood instantly"], llm: ["skip", "not needed"] }, true);
      this._sub("Understood instantly by built-in rules, no AI needed");
    } else if (entry.role === "info" && text.startsWith("Asking the language model")) {
      this.llmStart = performance.now();
      this._flow({ brain: ["done", "rules: no match → ask the LLM"], llm: ["on", "thinking on the GPU…"] }, true);
      this._sub(`No rule matches → asking the open LLM on ${this.llmPc}…`, "llm");
    } else if (entry.role === "info" && text.startsWith("Model plan")) {
      const took = (text.match(/\(([\d.]+) s\)/) || [])[1];
      const plan = text.replace(/^Model plan \([^)]*\):\s*/, "");
      this._flow({ llm: ["done", `planned in ${took} s`] }, true);
      this._sub(`The open LLM on ${this.llmPc} planned it in ${took} s: ${plan}`, "llm");
    } else if (entry.role === "error") {
      this._sub(text, "error");
    }
  }

  _status(status) {
    if (this.muted || status.skill === "stop") return;
    const what = (status.description || status.skill || "").trim();
    clearTimeout(this.settle);
    if (status.state === "running") {
      const moving = MOTION.has(status.skill);
      this._flow({
        brain: ["on", moving ? `${what}: inverse kinematics → MoveIt 2 path` : `${what}`],
        arm: moving ? ["on", "moving · simulated"] : ["", "simulated"],
      }, true);
    } else {
      this._flow({ brain: ["done", status.state === "succeeded" ? `${what}: done` : `${what}: ${status.state}`],
        arm: ["done", "simulated"] }, true);
      // Back to rest a moment after the last step, unless the hand is steering.
      this.settle = setTimeout(() => { if (!this.teleop) this._flow({}); }, 2500);
    }
  }

  _key(e) {
    if (e.key === "Escape") { this._do("escape"); return; }
    if (e.target.tagName === "INPUT" || e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
    if (this._do(e.key.toLowerCase())) e.preventDefault();
  }

  // A key, pressed or clicked in the cue column. Returns whether it was one of ours.
  _do(key) {
    if (key === "escape") this.actions.stop();
    else if (key === "v") this.tape.toggle();
    else if (key === "p") this.tape.pause();
    else if (key === "s") {
      this.setup.forEach((command) => { this.quiet.add(norm(command)); this.actions.send(command); });
      this.ready();
    } else if (key === "r") {
      this.ready();
      for (const li of $("rec-script").children) li.classList.remove("done");
    } else if (key === "e") { $("rec-end").hidden = !$("rec-end").hidden; this._hideHook(0); }
    else if (key === "h") this.actions.toggleHand();
    else if (key === "m") this.actions.toggleMic();
    else if (key === "/") $("command").focus();
    else return false;
    return true;
  }

  // ------------------------------------------------------------------ drawing

  // The webcam bubble. When something is wrong it says so inside the bubble, instead of black.
  async _camera() {
    const say = (text) => { $("rec-cam-msg").textContent = text; };
    say("Starting the camera…");
    try {
      const stream = await openCamera({ width: { ideal: 640 }, height: { ideal: 640 } });
      const video = $("rec-cam");
      video.srcObject = stream;
      await video.play().catch(() => {});
      const name = stream.getVideoTracks()[0]?.label || "the camera";
      say("");
      setTimeout(() => { if (!video.videoWidth) say(`No picture from ${name}. Click to retry.`); }, 3000);
    } catch (e) {
      say(e && e.name === "NotAllowedError"
        ? "Camera blocked: allow it for Chrome in System Settings → Privacy & Security → Camera, then click here."
        : `Camera error: ${(e && (e.message || e.name)) || e}. Click to retry.`);
    }
  }

  _hideHook(after) {
    clearTimeout(this.hookTimer);
    this.hookTimer = setTimeout(() => $("rec-hook").classList.add("hide"), after);
  }

  _caption(main, sub) {
    $("rec-caption-main").textContent = main;
    this._sub(sub);
  }

  _sub(text, kind = "") {
    $("rec-caption-sub").textContent = text;
    $("rec-caption-sub").className = kind;
  }

  // nodes: {you|brain|llm|arm: [state, text, title?]}; others go back to rest unless `keep`.
  // The GPU PC's box is the language model's, or Idol's while a scan runs there (its title).
  _flow(nodes, keep = false) {
    const rest = { you: "voice · text · hand", brain: "rules · inverse kinematics · MoveIt 2",
      llm: this.llmRest, arm: "simulated" };
    for (const name of ["you", "brain", "llm", "arm"]) {
      const el = $(`flow-${name}`);
      const span = el.querySelector("span");
      if (nodes[name]) {
        el.className = `node ${name} ${nodes[name][0]}`.trim();
        span.textContent = nodes[name][1];
        if (name === "llm") el.querySelector("b").textContent = nodes.llm[2] || "Open LLM, at home";
      } else if (!keep) {
        el.className = `node ${name}`;
        span.textContent = rest[name];
        if (name === "llm") el.querySelector("b").textContent = "Open LLM, at home";
      }
    }
  }
}
