import WebSocket from "ws";

let instance: RosbridgeClient | null = null;

export class RosbridgeClient {
  private ws: WebSocket | null = null;
  private url: string;
  private msgId = 0;

  constructor(url = "ws://ros2:9090") {
    this.url = url;
  }

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);
      this.ws.onopen = () => {
        console.log("rosbridge connected");
        resolve();
      };
      this.ws.onerror = (err) => {
        console.error("rosbridge error:", err);
        reject(err);
      };
      this.ws.onclose = () => {
        console.log("rosbridge disconnected");
        this.ws = null;
      };
    });
  }

  publishString(topic: string, data: string): void {
    if (!this.ws) return;
    this.ws.send(
      JSON.stringify({
        op: "publish",
        topic,
        msg: { data },
        id: `pub_${++this.msgId}`,
      })
    );
  }

  publishPoint(topic: string, x: number, y: number, z: number): void {
    if (!this.ws) return;
    this.ws.send(
      JSON.stringify({
        op: "publish",
        topic,
        msg: { x, y, z },
        id: `pub_${++this.msgId}`,
      })
    );
  }

  close(): void {
    this.ws?.close();
  }
}

export function getRosbridgeClient(url?: string): RosbridgeClient {
  if (!instance) {
    instance = new RosbridgeClient(url);
    instance.connect().catch(console.error);
  }
  return instance;
}
