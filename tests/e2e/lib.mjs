// Shared helpers for the browser test and the screenshot generator.
import { chromium } from "playwright";

export const BASE_URL = process.env.BASE_URL || "http://localhost:8080/";

export async function openApp({ width = 1440, height = 900, video = null } = {}) {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || undefined,
    // Software WebGL, so this also runs on machines without a GPU (CI).
    args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
      "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  });
  const context = await browser.newContext({
    viewport: { width, height },
    recordVideo: video ? { dir: video, size: { width, height } } : undefined,
  });
  const page = await context.newPage();
  const problems = [];
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
  await page.goto(BASE_URL);
  await page.waitForFunction(() => window.mtb && window.mtb.ready(), null, { timeout: 180000 });
  await page.waitForTimeout(1500);        // meshes finish loading
  return { browser, context, page, problems };
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Type a command like a person would, then press Enter.
export async function say(page, text, { typing = 0 } = {}) {
  await page.click("#command");
  await page.fill("#command", "");
  if (typing) {
    // Looks like typing in the recording, without one slow key event per character.
    for (let i = 2; i < text.length; i += 2) {
      await page.evaluate((t) => { document.getElementById("command").value = t; }, text.slice(0, i));
      await sleep(typing * 2);
    }
  }
  await page.fill("#command", text);
  await page.keyboard.press("Enter");
}

export const idle = (page, timeout = 90000) => page.waitForFunction(
  () => window.mtb.state && !window.mtb.state.busy && window.mtb.state.queue === 0
    && !(window.mtb.agent && window.mtb.agent.busy), null, { timeout });

export async function sayAndWait(page, text, options = {}) {
  await say(page, text, options);
  await sleep(700);
  await idle(page);
  await sleep(300);
}

export const object = (page, name) => page.evaluate(
  (n) => window.mtb.objects.find((o) => o.name === n) || null, name);

export const holding = (page, name, timeout = 60000) => page.waitForFunction(
  (n) => window.mtb.state.holding === n, name, { timeout });

// Move the synthetic hand smoothly: `from` and `to` are {x, y, size, pinch} in camera-image units.
export async function moveHand(page, from, to, ms = 1200) {
  const steps = Math.max(2, Math.round(ms / 50));
  for (let i = 1; i <= steps; i++) {
    const t = i / steps, k = t * t * (3 - 2 * t);
    await page.evaluate((h) => window.mtb.feedHand(h), {
      x: from.x + (to.x - from.x) * k, y: from.y + (to.y - from.y) * k,
      size: from.size + (to.size - from.size) * k, pinch: t > 0.5 ? to.pinch : from.pinch,
    });
    await sleep(50);
  }
}

export async function holdHand(page, pose, ms) {
  await moveHand(page, pose, pose, ms);
}
