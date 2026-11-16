// Generates the pictures and the demo clip used in the README and docs, by driving the real app:
// every frame shows motions planned by MoveIt and executed through ros2_control.
//
//   cd tests/e2e && npm install && npx playwright install chromium
//   node screenshots.mjs            (output: docs/media/)
//
// The GitHub workflow .github/workflows/screenshots.yml runs this after every change.
import { mkdir, readdir, rename, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { holdHand, holding, idle, moveHand, openApp, say, sayAndWait, sleep } from "./lib.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(process.env.OUT || join(here, "../../docs/media"));
const VIDEO = join(OUT, "_video");
await mkdir(OUT, { recursive: true });
await rm(VIDEO, { recursive: true, force: true });

const { browser, context, page } = await openApp({ width: 1280, height: 720, video: VIDEO });
const view = async (name) => { await page.click(`#views [data-view="${name}"]`); await sleep(900); };
const shot = async (name) => {
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  console.log(`saved ${name}.png`);
};
const typing = 28;

await sayAndWait(page, "clear the table");
await page.evaluate(() => { document.getElementById("log").innerHTML = ""; });
await view("side");
const started = Date.now();
await shot("01-ready");

// 1. Create objects with one sentence.
await sayAndWait(page, "create an apple, a mug on the right and a red cube on the left", { typing });
await sleep(600);
await shot("02-objects");

// 2. Pick and place, understood by the built-in rules and planned by MoveIt.
await say(page, "put the apple on the cube", { typing });
await holding(page, "apple");
await sleep(700);
await shot("03-carrying");
await idle(page);
await sleep(800);
await shot("04-stacked");

// 3. A longer request: several steps from one sentence.
await sayAndWait(page, "move the mug to the front, then go home", { typing });
await sleep(600);
await shot("05-sequence");

// 4. Hand control (a synthetic hand stands in for the webcam): steer, pinch, carry, release.
await view("operator");
await page.evaluate(() => window.mtb.teleop(true));
const rest = { x: 0.5, y: 0.5, size: 0.18, pinch: false };
await holdHand(page, rest, 1500);
const mug = await page.evaluate(() => window.mtb.objects.find((o) => o.name === "mug").position);
// Invert the hand mapping (web/js/hand.js) to find the hand pose that puts the jaws on the mug.
const handFor = (x, y, z) => ({
  x: 1 - (0.5 - y / 0.80), y: 0.85 - ((z - 0.02) / 0.28) * 0.65, size: 0.18 * (1 + (x - 0.21) / 0.32),
});
const above = { ...handFor(mug[0], mug[1], 0.16), pinch: false };
const at = { ...handFor(mug[0], mug[1], 0.045), pinch: false };
await moveHand(page, rest, above, 1500);
await holdHand(page, above, 700);
await moveHand(page, above, at, 1300);
await holdHand(page, at, 1500);
await holdHand(page, { ...at, pinch: true }, 1300);
const lifted = { ...handFor(0.22, 0.12, 0.17), pinch: true };
await moveHand(page, { ...at, pinch: true }, lifted, 1800);
await holdHand(page, lifted, 600);
await shot("06-hand-control");
const down = { ...handFor(0.22, 0.12, 0.06), pinch: true };
await moveHand(page, lifted, down, 1200);
await holdHand(page, down, 600);
await holdHand(page, { ...down, pinch: false }, 1000);
await moveHand(page, { ...down, pinch: false }, { ...handFor(0.2, 0.0, 0.18), pinch: false }, 1200);
await page.evaluate(() => window.mtb.teleop(false));
await view("side");

await sayAndWait(page, "go home", { typing });
await sleep(800);
const seconds = (Date.now() - started) / 1000;

await context.close();                      // finishes the video file
await browser.close();
const [file] = (await readdir(VIDEO)).filter((f) => f.endsWith(".webm"));
await rename(join(VIDEO, file), join(OUT, "demo.webm"));
await rm(VIDEO, { recursive: true, force: true });
console.log(`saved demo.webm (${seconds.toFixed(0)} s of demo)`);
