// A small rosbridge client: publish and subscribe to ROS topics over a websocket.
// It reconnects by itself and re-creates subscriptions, so the page survives a restart of ROS.

export class Ros {
  constructor(url) {
    this.url = url;
    this.connected = false;
    this.subscriptions = new Map();   // topic -> {type, callback, throttle}
    this.advertised = new Map();      // topic -> type
    this.listeners = [];
    this._connect();
  }

  onStatus(callback) {
    this.listeners.push(callback);
    callback(this.connected);
  }

  _connect() {
    const socket = new WebSocket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      this.connected = true;
      for (const [topic, type] of this.advertised) this._send({ op: "advertise", topic, type });
      for (const [topic, s] of this.subscriptions) this._sendSubscribe(topic, s);
      this.listeners.forEach((l) => l(true));
    };
    socket.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      if (data.op !== "publish") return;
      const s = this.subscriptions.get(data.topic);
      if (s) s.callback(data.msg);
    };
    socket.onclose = () => {
      const was = this.connected;
      this.connected = false;
      if (was) this.listeners.forEach((l) => l(false));
      setTimeout(() => this._connect(), 1500);
    };
    socket.onerror = () => socket.close();
  }

  _send(message) {
    if (this.connected && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  _sendSubscribe(topic, s) {
    const message = { op: "subscribe", topic, type: s.type, throttle_rate: s.throttle, queue_length: s.queue };
    if (s.latched) message.qos = { durability: "transient_local", depth: 1 };
    this._send(message);
  }

  // queue: how many messages rosbridge keeps for a slow browser. 1 suits state topics (only the
  // newest matters); event topics such as the conversation need more, or lines get lost.
  subscribe(topic, type, callback, { throttle = 0, latched = false, queue = 1 } = {}) {
    const s = { type, callback, throttle, latched, queue };
    this.subscriptions.set(topic, s);
    if (this.connected) this._sendSubscribe(topic, s);
  }

  publish(topic, type, msg) {
    if (!this.advertised.has(topic)) {
      this.advertised.set(topic, type);
      this._send({ op: "advertise", topic, type });
    }
    return this._send({ op: "publish", topic, msg });
  }

  string(topic, data) { return this.publish(topic, "std_msgs/String", { data }); }
  bool(topic, data) { return this.publish(topic, "std_msgs/Bool", { data }); }
  json(topic, object) { return this.string(topic, JSON.stringify(object)); }
}
