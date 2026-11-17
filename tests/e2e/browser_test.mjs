// Browser end-to-end test: the real page, talking to the real ROS stack through rosbridge.
//   cd tests/e2e && npm install && npx playwright install chromium && node browser_test.mjs
import assert from "node:assert/strict";
import { holdHand, moveHand, object, openApp, sayAndWait, sleep } from "./lib.mjs";

const { browser, page, problems } = await openApp();
const check = async (name, fn) => {
  try { await fn(); console.log(`ok    ${name}`); } catch (e) { console.log(`FAIL  ${name}\n      ${e.message}`); process.exitCode = 1; }
};

await sayAndWait(page, "clear the table");

await check("the robot model is loaded with all its joints", async () => {
  const joints = await page.evaluate(() => Object.values(window.mtb.viewer.robot.joints)
    .filter((j) => j.jointType !== "fixed").map((j) => j.name));
  for (const name of ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]) {
    assert.ok(joints.includes(name), `missing joint ${name}`);
  }
  const meshes = await page.evaluate(() => { let n = 0; window.mtb.viewer.robot.traverse((o) => { if (o.isMesh) n++; }); return n; });
  assert.ok(meshes >= 10, `only ${meshes} meshes loaded`);
});

await check("status pills show a connected, ready robot", async () => {
  assert.match(await page.textContent("#pill-ros"), /Connected/);
  assert.match(await page.textContent("#pill-robot"), /ready/i);
});

await check("the 3D robot follows the joint states from ROS", async () => {
  const before = await page.evaluate(() => window.mtb.viewer.robot.joints.shoulder_pan.angle);
  await sayAndWait(page, "move to the left");
  const after = await page.evaluate(() => window.mtb.viewer.robot.joints.shoulder_pan.angle);
  assert.ok(Math.abs(after - before) > 0.2, `shoulder_pan did not move (${before} -> ${after})`);
});

await check("a typed command creates objects in the 3D scene", async () => {
  await sayAndWait(page, "create an apple and a red cube on the left");
  assert.ok(await object(page, "apple"), "no apple in the scene data");
  // Drawing follows the data a few frames later, and frames are slow without a GPU: wait for it.
  await page.waitForFunction(() => window.mtb.viewer.objects.size === 2
    && document.querySelectorAll(".object-label").length === 2, null, { timeout: 30000 });
  const drawn = await page.evaluate(() => [...window.mtb.viewer.objects.keys()]);
  assert.deepEqual(drawn.sort(), ["apple", "red cube"]);
  const labels = await page.$$eval(".object-label", (els) => els.map((e) => e.textContent).sort());
  assert.deepEqual(labels, ["apple", "red cube"]);
});

await check("pick and place from the browser, with the conversation shown", async () => {
  await sayAndWait(page, "put the apple on the cube");
  const apple = await object(page, "apple"), cube = await object(page, "red cube");
  assert.ok(Math.hypot(apple.position[0] - cube.position[0], apple.position[1] - cube.position[1]) < 0.012);
  assert.ok(apple.position[2] > cube.position[2]);
  await page.waitForFunction(() => [...document.querySelectorAll("#log .entry.robot")]
    .some((e) => /Put the apple on the red cube/.test(e.textContent)), null, { timeout: 30000 }).catch(() => {});
  const log = await page.$$eval("#log .entry", (els) => els.map((e) => `${e.className}: ${e.textContent}`));
  assert.ok(log.some((l) => l.includes("user") && l.includes("put the apple on the cube")), log.join(" | "));
  assert.ok(log.some((l) => l.includes("robot") && /Put the apple on the red cube/.test(l)), log.join(" | "));
});

await check("errors are shown in plain words", async () => {
  await sayAndWait(page, "grab the banana");
  const errors = await page.$$eval("#log .entry.error", (els) => els.map((e) => e.textContent));
  assert.ok(errors.some((t) => /no banana/.test(t)), errors.join(" | "));
});

await check("buttons work: Clear table", async () => {
  await page.click("#btn-clear");
  await page.waitForFunction(() => window.mtb.objects.length === 0, null, { timeout: 30000 });
});

await check("hand control: the gripper follows the hand, a pinch grabs", async () => {
  await sayAndWait(page, "create a cube at 0.24 0.0");
  await page.evaluate(() => window.mtb.teleop(true));
  const centre = { x: 0.5, y: 0.5, size: 0.18, pinch: false };
  await holdHand(page, centre, 1500);                          // calibrates the neutral distance
  const start = await page.evaluate(() => window.mtb.state.tool);
  await moveHand(page, centre, { x: 0.3, y: 0.35, size: 0.18, pinch: false }, 1000);
  await holdHand(page, { x: 0.3, y: 0.35, size: 0.18, pinch: false }, 1500);
  const moved = await page.evaluate(() => window.mtb.state.tool);
  // Hand to the right of the (mirrored) screen -> gripper to the robot's right (y gets smaller).
  assert.ok(moved[1] < start[1] - 0.05, `gripper did not follow sideways: ${start} -> ${moved}`);
  assert.ok(moved[2] > 0.12, `gripper did not follow upwards: ${moved}`);
  // Lower the open hand over the cube, pinch, lift.
  const over = { x: 0.5, y: 0.82, size: 0.199, pinch: false };
  await moveHand(page, { x: 0.3, y: 0.35, size: 0.18, pinch: false }, over, 1500);
  await holdHand(page, over, 2000);
  await holdHand(page, { ...over, pinch: true }, 1500);
  assert.equal(await page.evaluate(() => window.mtb.state.holding), "cube");
  await moveHand(page, { ...over, pinch: true }, { x: 0.5, y: 0.45, size: 0.199, pinch: true }, 1200);
  await holdHand(page, { x: 0.5, y: 0.45, size: 0.199, pinch: true }, 800);
  const cube = await object(page, "cube");
  assert.ok(cube.held && cube.position[2] > 0.08, `cube was not lifted: ${JSON.stringify(cube)}`);
  await holdHand(page, { x: 0.5, y: 0.45, size: 0.199, pinch: false }, 1200);
  assert.equal(await page.evaluate(() => window.mtb.state.holding), null);
  await page.evaluate(() => window.mtb.teleop(false));
});

if (process.env.CHECK_HAND_TRACKING === "1") {
  await check("the hand-tracking model loads in the browser (MediaPipe)", async () => {
    const loaded = await page.evaluate(async () => {
      const { loadHandLandmarker } = await import("./js/hand.js");
      const landmarker = await loadHandLandmarker();
      return typeof landmarker.detectForVideo === "function";
    });
    assert.ok(loaded);
  });
}

// The optional object scanner (./run.sh --scan). In CI it runs with IDOL_BACKEND=file, so the
// browser's fake camera, the upload, the conversion and "create a <name>" are all real.
if (process.env.CHECK_SCAN === "1") {
  await check("scan: four sides, started by saying “scan a stapler, 8 cm”, become an object", async () => {
    await page.waitForSelector("#btn-scan:not([hidden])", { timeout: 10000 });
    await page.fill("#command", "scan a stapler, 8 cm");
    await page.press("#command", "Enter");
    await page.waitForFunction(() => !document.getElementById("scan-panel").hidden);
    assert.equal(await page.inputValue("#scan-name"), "stapler");
    assert.equal(await page.inputValue("#scan-height"), "8");
    assert.ok(await page.isChecked("#scan-mode-sides"), "four sides by default with a GPU-less test backend");
    await page.waitForFunction(() => window.mtb.scanner.state === "capturing", null, { timeout: 10000 });
    // Space takes each photo without waiting for the countdown.
    for (let k = 1; k <= 4; k++) {
      await page.waitForFunction((k) => document.querySelectorAll("#scan-thumbs img").length === k - 1, k);
      await page.keyboard.press(" ");
      await page.waitForFunction((k) => document.querySelectorAll("#scan-thumbs img").length >= k, k, { timeout: 5000 });
    }
    await page.waitForFunction(() => window.mtb.objects.some((o) => o.name === "stapler"), null, { timeout: 120000 });
    const stapler = await object(page, "stapler");
    assert.match(stapler.model, /^\/models\/cache\/stapler_.*\.glb$/);
    assert.ok(Math.abs(stapler.size[2] - 0.08) < 0.001, `height ${stapler.size[2]}`);
    assert.ok(await page.evaluate(() => document.getElementById("scan-panel").hidden), "the panel closes");
  });
  await sayAndWait(page, "clear the table");

  await check("scan: a thumbs-up to the camera starts it; one photo", async () => {
    await page.click("#btn-scan");
    await page.waitForFunction(() => document.getElementById("scan-cam").videoWidth > 0, null, { timeout: 10000 });
    await page.fill("#scan-name", "Teapot");
    await page.check("#scan-mode-photo");
    await page.evaluate(() => document.activeElement.blur());
    // What the hand tracker would report for a thumbs-up held 0.7 s (its own clock: the page is slow here).
    await page.evaluate(async () => {
      const { fakeThumbsUp } = await import("./js/hand.js");
      const start = performance.now();
      for (let t = 0; t <= 7; t++) window.mtb.scanner.seeHand(fakeThumbsUp(), start + 100 * t);
    });
    await page.waitForFunction(() => window.mtb.objects.some((o) => o.name === "teapot"), null, { timeout: 60000 })
      .catch(async () => {
        const why = await page.evaluate(() => [window.mtb.scanner.state, document.getElementById("scan-status").textContent,
          window.mtb.objects.map((o) => o.name).join(",")].join(" | "));
        throw new Error(`no teapot: ${why}`);
      });
  });
  await sayAndWait(page, "clear the table");
}

await check("no JavaScript errors on the page", async () => {
  const real = problems.filter((p) => !/favicon|GPU stall|ReadPixels/.test(p));
  assert.deepEqual(real, []);
});

await sayAndWait(page, "clear the table");
await sleep(200);
await browser.close();
console.log(process.exitCode ? "\nBrowser test FAILED" : "\nBrowser test passed");
