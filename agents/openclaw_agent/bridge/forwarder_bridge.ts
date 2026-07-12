import { createClient } from "openclaw-sdk";
import * as readline from "readline";

const GATEWAY_URL = process.env.OPENCLAW_GATEWAY_URL || "ws://openclaw:1455";
const AGENT_ID = process.env.OPENCLAW_AGENT_ID || "main";

async function main() {
  let client: any;

  try {
    client = createClient({ url: GATEWAY_URL });
    await client.connect();
    console.error(`Connected to OpenClaw Gateway at ${GATEWAY_URL}`);
  } catch (err) {
    console.error(`Failed to connect to Gateway: ${err}`);
    process.exit(1);
  }

  const rl = readline.createInterface({ input: process.stdin });

  for await (const line of rl) {
    try {
      const msg = JSON.parse(line);

      if (msg.type === "task") {
        // Send as a direct task to the agent
        const result = await client.send(AGENT_ID, msg.data);
        process.stdout.write(JSON.stringify({ ok: true, response: result }) + "\n");
      } else if (msg.type === "context") {
        // Send as context (no response expected)
        await client.sendContext(AGENT_ID, msg.data);
        process.stdout.write(JSON.stringify({ ok: true }) + "\n");
      } else {
        process.stderr.write(JSON.stringify({ error: `Unknown message type: ${msg.type}` }) + "\n");
      }
    } catch (err: any) {
      process.stderr.write(JSON.stringify({ error: String(err) }) + "\n");
    }
  }
}

main().catch((err) => {
  console.error(`Fatal: ${err}`);
  process.exit(1);
});
