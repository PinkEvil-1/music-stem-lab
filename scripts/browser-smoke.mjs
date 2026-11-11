import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const work = path.join(root, ".tmp", "browser-" + Date.now());
mkdirSync(work, { recursive: true });
const browsers = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];
const browserPath = process.env.MUSIC_STEM_TEST_BROWSER || browsers.find(existsSync);
if (!browserPath) throw new Error("No supported local browser found; set MUSIC_STEM_TEST_BROWSER.");
const python = process.platform === "win32" ? path.join(root, ".venv", "Scripts", "python.exe") : path.join(root, ".venv", "bin", "python");
const port = await new Promise((resolve) => {
  const socket = createServer();
  socket.listen(0, "127.0.0.1", () => { const value = socket.address().port; socket.close(() => resolve(value)); });
});
const base = "http://127.0.0.1:" + port;
const checkpoint = process.env.MUSIC_STEM_TEST_CHECKPOINT;
const serverArgs = ["-m", "music_stem_lab", "--port", String(port)];
if (checkpoint) serverArgs.push("--model-checkpoint", checkpoint);
const server = spawn(python, serverArgs, {
  cwd: root, windowsHide: true, stdio: "ignore",
  env: { ...process.env, MUSIC_STEM_DATA_DIR: path.join(work, "data"), MUSIC_STEM_WORKER_TOKEN: "" },
});
let browser, cdp;
const delay = (ms) => new Promise(r => setTimeout(r, ms));
async function until(check, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { try { const result = await check(); if (result) return result; } catch {} await delay(100); }
  throw new Error("Browser check timed out");
}
class CDP {
  constructor(socket) {
    this.socket = socket; this.nextId = 0; this.pending = new Map(); this.errors = [];
    socket.addEventListener("message", ({data}) => {
      const value = JSON.parse(data);
      if (value.id) { const pair = this.pending.get(value.id); if (pair) { this.pending.delete(value.id); value.error ? pair.reject(new Error(value.error.message)) : pair.resolve(value.result); } }
      if (value.method === "Runtime.exceptionThrown") this.errors.push(value.params.exceptionDetails.text);
      if (value.method === "Log.entryAdded" && value.params.entry.level === "error") this.errors.push(value.params.entry.text);
    });
  }
  call(method, params = {}) {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error("CDP command timed out: " + method)); }, 15000);
      this.pending.set(id, { resolve: v => { clearTimeout(timer); resolve(v); }, reject: e => { clearTimeout(timer); reject(e); } });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const value = await this.call("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true, userGesture: true });
    if (value.exceptionDetails) throw new Error("Browser evaluation failed");
    return value.result.value;
  }
}
try {
  await until(async () => (await fetch(base + "/api/capabilities")).ok);
  const profile = path.join(work, "browser-profile");
  browser = spawn(browserPath, [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-background-networking", "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
    "--user-data-dir=" + profile, base,
  ], { windowsHide: true, stdio: "ignore" });
  const activePort = path.join(profile, "DevToolsActivePort");
  await until(() => existsSync(activePort));
  const debugPort = readFileSync(activePort, "utf8").split(/\r?\n/)[0];
  const debugBase = "http://127.0.0.1:" + debugPort;
  const target = await until(async () => (await (await fetch(debugBase + "/json/list")).json()).find(t => t.type === "page" && t.url.startsWith(base)));
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, {once: true}); socket.addEventListener("error", reject, {once: true}); });
  cdp = new CDP(socket);
  await cdp.call("Runtime.enable");
  await cdp.call("Log.enable");
  await cdp.call("Page.enable");
  await cdp.call("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await until(() => cdp.evaluate("document.querySelector('#service-note').textContent.includes('工作室已就緒')"));
  assert.equal(await cdp.evaluate("document.querySelector('#extra-exports').disabled"), true);
  if (checkpoint) {
    await cdp.evaluate("document.querySelector('input[value=separate]').click(); true");
    await until(() => cdp.evaluate("Boolean(state.hardware?.gpu && state.hardware?.ram)"));
    assert.equal(await cdp.evaluate("document.querySelector('#model-options').hidden"), false);
    assert.equal(await cdp.evaluate("document.querySelector('#model-preset').value"), "balanced");
    const result = await cdp.evaluate(`(() => {
      const select = document.querySelector('#model-preset');
      const rows = Array.from(select.options, option => {
        select.value = option.value;
        select.dispatchEvent(new Event('change'));
        return Array.from(document.querySelectorAll('.resource-row'), row => row.lastChild.className);
      });
      return { rows, actual: state.hardware };
    })()`);
    const expectedClass = (mib, threshold) => mib >= threshold * 1024 ? "resource-ok" : "resource-low";
    assert.deepEqual(result.rows, [[3, 4], [5, 6], [7, 8]].map(([vram, ram]) => [
      expectedClass(result.actual.gpu.available_mib, vram),
      expectedClass(result.actual.ram.available_mib, ram),
    ]));
    assert.match(result.actual.gpu.name, /NVIDIA/i);
    assert.equal(await cdp.evaluate("document.querySelector('#model-description').textContent.includes('50%')"), true);
    await cdp.call("Page.captureScreenshot", { format: "png", captureBeyondViewport: true })
      .then(r => writeFileSync(path.join(work, "model-hardware.png"), Buffer.from(r.data, "base64")));
  }
  await cdp.evaluate("document.querySelector('#example').click(); true");
  assert.equal(await cdp.evaluate("document.querySelector('#model-options').hidden"), true);
  assert.equal(await cdp.evaluate("document.querySelector('#export-no-vocals').checked || document.querySelector('#export-no-guitar').checked"), false);
  await cdp.evaluate("document.querySelector('#export-no-vocals').click(); true");
  assert.equal(await cdp.evaluate("document.querySelector('#export-no-guitar').checked"), false);
  await cdp.evaluate("document.querySelector('#export-no-guitar').click(); document.querySelector('input[value=download_audio]').click(); true");
  assert.equal(await cdp.evaluate("document.querySelector('#extra-exports').disabled"), true);
  await cdp.evaluate("document.querySelector('input[value=separate]').click(); document.querySelector('#submit').click(); true");
  await until(() => cdp.evaluate("document.querySelector('#count-completed').textContent === '2'"), 25000);
  assert.equal(await cdp.evaluate("document.querySelectorAll('.job').length"), 2);
  await cdp.evaluate("document.querySelector('.job-actions button').click(); true");
  await until(() => cdp.evaluate("document.querySelector('#job-dialog').open"));
  assert.equal(await cdp.evaluate("document.querySelectorAll('#job-detail audio').length"), 9);
  const jobs = await (await fetch(base + "/api/jobs")).json();
  for (const job of jobs.items) {
    assert.deepEqual(job.extra_exports, ["no_guitar", "no_vocals"]);
    assert.equal(job.native_stems.length, 6);
    assert.equal(job.artifacts.length, 10);
  }
  const playback = await cdp.evaluate("(async () => { const audio = document.querySelector('#job-detail audio'); audio.muted = true; await audio.play(); await new Promise(r => setTimeout(r, 150)); const result = { duration: audio.duration, advancing: audio.currentTime > 0, playing: !audio.paused }; audio.pause(); return result; })()");
  assert.equal(playback.duration, 1);
  assert.equal(playback.advancing, true);
  assert.equal(playback.playing, true);
  const audioURL = await cdp.evaluate("document.querySelector('#job-detail audio').src");
  assert.equal((await fetch(audioURL, { headers: { Range: "bytes=0-15" } })).status, 206);
  await cdp.evaluate("document.querySelector('#close-dialog').click(); true");
  await cdp.call("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }).then(r => writeFileSync(path.join(work, "desktop.png"), Buffer.from(r.data, "base64")));
  await cdp.call("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  assert.equal(await cdp.evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
  await cdp.call("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }).then(r => writeFileSync(path.join(work, "mobile.png"), Buffer.from(r.data, "base64")));
  assert.deepEqual(cdp.errors, []);
  const result = { result: "PASS", checks: ["server_http", "browser_submit_two_jobs", "demo_fifo_completion", "artifact_dialog", "audio_range", "independent_export_checkboxes", "export_options_persisted", "wav_playback", "mobile_no_overflow", "no_browser_errors"], screenshots: [path.join(work, "desktop.png"), path.join(work, "mobile.png")] };
  if (checkpoint) {
    result.checks.push("real_gpu_and_ram", "preset_resource_colors");
    result.screenshots.push(path.join(work, "model-hardware.png"));
  }
  writeFileSync(path.join(work, "result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} finally {
  if (cdp) { try { await cdp.call("Browser.close"); } catch {} cdp.socket.close(); }
  else if (browser && browser.exitCode === null) browser.kill();
  if (server.exitCode === null) server.kill();
}
