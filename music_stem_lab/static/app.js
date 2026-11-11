"use strict";
const $ = (selector) => document.querySelector(selector);
const state = { capabilities: null, hardware: undefined, hardwareAt: 0, hardwarePending: false, offset: 0, limit: 20, busy: false, fingerprint: null, key: null, signature: null, dialogJob: null };
const labels = { queued: "排隊中", running: "處理中", publishing: "儲存中", recovering: "待恢復", completed: "已完成", failed: "失敗", cancelled: "已取消", deleting: "刪除中" };
const modes = { download_audio: "下載音訊", separate: "模型分軌", remove_vocals: "去人聲", remove_guitar: "去吉他" };
const stages = { fetching: "取得來源", decoding: "解碼音訊", separating: "分離音源", mixing: "製作伴奏", verifying: "驗證檔案" };
const kinds = { source: "來源音訊", drums: "鼓", bass: "低音", piano: "鋼琴", other: "其他音源", vocals: "人聲", no_vocals: "無人聲伴奏", guitar: "吉他", no_guitar: "無吉他伴奏", manifest: "處理紀錄" };
function el(tag, className, text) { const n = document.createElement(tag); if (className) n.className = className; if (text !== undefined) n.textContent = text; return n; }
function size(bytes) { if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KiB"; if (bytes < 1024 ** 3) return (bytes / 1024 ** 2).toFixed(1) + " MiB"; return (bytes / 1024 ** 3).toFixed(2) + " GiB"; }
function date(seconds) { return new Date(seconds * 1000).toLocaleString("zh-TW", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); }
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", ...options.headers } });
  if (response.status === 204) return null;
  const body = await response.json();
  if (!response.ok) { const error = new Error(body.error?.message || "操作失敗，請稍後重試。"); error.body = body; throw error; }
  return body;
}
function toast(message) { $("#toast").textContent = message; $("#toast").hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { $("#toast").hidden = true; }, 4500); }
function selectedExports() { return [...document.querySelectorAll('input[name="extra_exports"]:checked')].map(input => input.value); }
function exportSummary(job) {
  if (job.mode !== "separate") return "";
  const selected = job.extra_exports || [];
  const preset = state.capabilities?.model_presets?.find(p => p.id === job.model_preset);
  const outputs = selected.length ? "額外輸出：" + selected.map(kind => kinds[kind] || kind).join("、") : "僅原生音軌，無額外伴奏";
  return preset ? preset.label + " · " + outputs : outputs;
}
function resourceRow(label, actual, suggestedGiB) {
  const row = el("div", "resource-row");
  row.append(el("strong", "", label), el("span", "", "建議可用 " + suggestedGiB + " GiB"));
  if (!actual) {
    row.append(el("span", "", "無法讀取"));
    return row;
  }
  const sufficient = actual.available_mib >= suggestedGiB * 1024;
  const available = (actual.available_mib / 1024).toFixed(2);
  const total = (actual.total_mib / 1024).toFixed(2);
  row.append(el("span", sufficient ? "resource-ok" : "resource-low",
    "可用 " + available + " / 共 " + total + " GiB · " + (sufficient ? "達到建議" : "低於建議")));
  return row;
}
function renderHardware(preset) {
  const target = $("#model-hardware");
  if (state.hardware === undefined) {
    target.textContent = "正在讀取本機硬體…";
    return;
  }
  const gpu = state.hardware?.gpu;
  target.replaceChildren(
    resourceRow(gpu ? gpu.name + " 顯示記憶體" : "CUDA 顯示記憶體", gpu, preset.vram_gib),
    resourceRow("系統記憶體", state.hardware?.ram, preset.ram_gib),
    el("p", "export-note", "建議值為可用記憶體的參考。需求會隨音訊長度與同時執行的程式而變動。")
  );
}
async function refreshHardware() {
  if ($("#model-options").hidden || state.hardwarePending || Date.now() - state.hardwareAt < 10000) return;
  state.hardwarePending = true;
  try {
    state.hardware = await api("/api/hardware");
  } catch {
    state.hardware = null;
  } finally {
    state.hardwareAt = Date.now();
    state.hardwarePending = false;
    showModelPreset();
  }
}
function showModelPreset() {
  const preset = state.capabilities?.model_presets?.find(p => p.id === $("#model-preset").value);
  if (!preset) return;
  $("#model-description").textContent = preset.description + " " + preset.segment_seconds + " 秒分段 · " + Math.round(preset.overlap * 100) + "% 重疊 · 時移次數 " + preset.shifts;
  renderHardware(preset);
}
function executionNote() {
  const demo = $("#demo").checked;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  $("#extra-exports").disabled = mode !== "separate";
  $("#model-options").hidden = demo || mode !== "separate" || !$("#model-preset").value;
  void refreshHardware();
  $("#execution-note").textContent = demo ? "示範會產生合成音，僅驗證排隊與檔案流程。" : mode !== "download_audio" ? (state.capabilities?.model_inference_available ? "將使用這台電腦的 GPU 分軌。請確認你具有音源使用權利。" : "提交後會排隊等待模型執行器。") : state.capabilities?.download_enabled ? "將取得原始音訊格式；請確認你具有適當使用權利。" : "來源下載尚未啟用；提交後會排隊等待執行器。";
}
async function capabilities() {
  state.capabilities = await api("/api/capabilities");
  const select = $("#model-preset");
  const presets = state.capabilities.model_presets || [];
  if (select.options.length !== presets.length) {
    const previous = select.value;
    select.replaceChildren(...presets.map(preset => new Option(preset.label + " · " + preset.model, preset.id)));
    select.value = presets.some(p => p.id === previous) ? previous : state.capabilities.default_model_preset;
    showModelPreset();
  }
  const storage = state.capabilities.storage;
  $("#storage-label").textContent = size(storage.used_bytes) + " / " + size(storage.quota_bytes);
  $("#storage-meter").value = Math.min(100, storage.used_bytes / storage.quota_bytes * 100);
  $("#service-note").textContent = state.capabilities.model_inference_available ? "工作室已就緒 · 本機 GPU 分軌已啟用。" : "工作室已就緒 · 可管理佇列或試用示範流程。";
  executionNote();
}
function description(job) {
  if (job.state === "queued") return "佇列第 " + job.queue_position + " 筆" + (job.execution_kind === "real" && job.mode !== "download_audio" ? " · 等待模型執行器" : " · 等待執行器");
  if (job.state === "recovering") return "請確認舊執行器已停止，再恢復佇列。";
  if (job.cancel_requested && ["running", "publishing"].includes(job.state)) return "取消中，等待執行器停止並確認。";
  if (job.state === "completed") return job.execution_kind === "demo" ? "合成測試音已儲存，並非歌曲分軌結果。" : "檔案已儲存，可開啟詳情試聽與下載。";
  return stages[job.stage] || job.error_message || labels[job.state];
}
function action(label, handler) {
  const button = el("button", "secondary", label); button.type = "button";
  button.addEventListener("click", async () => { button.disabled = true; try { await handler(); await refresh(true); } catch (error) { toast(error.message); } finally { button.disabled = false; } });
  return button;
}
async function mutate(job, verb) { return api("/api/jobs/" + job.id + "/" + verb, { method: "POST" }); }
function resultFolderButton(job) {
  return action("開啟結果資料夾", () => api("/api/jobs/" + job.id + "/open-folder", {
    method: "POST", headers: { "X-Music-Stem-Local": "1" },
  }));
}
function canOpenResultFolder(job) {
  return job.state === "completed" && state.capabilities?.local_folder_enabled;
}
function renderJob(job) {
  const row = el("article", "job"), top = el("div", "job-top"), heading = el("div");
  const title = el("div", "job-title", modes[job.mode] + " · " + job.video_id);
  if (job.execution_kind === "demo") title.append(el("span", "badge demo", "示範"));
  heading.append(title, el("div", "job-meta", date(job.created_at) + " · 第 " + job.attempt_count + " 次執行"));
  top.append(heading, el("span", "badge " + job.state, labels[job.state]));
  row.append(top, el("p", "job-description", description(job)));
  if (job.mode === "separate") row.append(el("p", "job-export-summary", exportSummary(job)));
  if (job.progress !== null && job.state === "running") { const progress = el("progress"); progress.max = 100; progress.value = job.progress; progress.setAttribute("aria-label", "工作進度"); row.append(progress); }
  if (job.error_message && job.state === "failed") row.append(el("p", "job-error", job.error_message));
  const actions = el("div", "job-actions");
  actions.append(action("詳情與檔案", () => showDetail(job.id)));
  if (canOpenResultFolder(job)) actions.append(resultFolderButton(job));
  if (["queued", "running", "publishing"].includes(job.state) && !job.cancel_requested) actions.append(action("取消", () => mutate(job, "cancel")));
  if (["failed", "cancelled"].includes(job.state)) actions.append(action("重試", () => mutate(job, "retry")));
  if (job.state === "recovering") actions.append(action("恢復", async () => {
    if (confirm("請先確認舊執行器及其子程序已完全停止。你確認已停止，並撤銷舊執行權嗎？")) await api("/api/jobs/" + job.id + "/recover", { method: "POST", body: JSON.stringify({ old_worker_stopped: true }) });
  }));
  if (["queued", "completed", "failed", "cancelled", "deleting"].includes(job.state)) actions.append(action("刪除", async () => {
    if (confirm("確定刪除這筆工作及其所有音訊檔案？")) { await api("/api/jobs/" + job.id, { method: "DELETE" }); if (state.dialogJob === job.id) $("#job-dialog").close(); }
  }));
  row.append(actions); return row;
}
async function showDetail(id) {
  const job = await api("/api/jobs/" + id); state.dialogJob = id;
  const fragment = document.createDocumentFragment();
  if (job.execution_kind === "demo") fragment.append(el("div", "notice", "示範結果：以下是合成測試音，沒有下載或分離 YouTube 歌曲。"));
  fragment.append(el("p", "detail-meta", modes[job.mode] + " · " + job.video_id + " · " + labels[job.state]), el("p", "detail-meta", "工作 ID：" + job.id));
  const sourceLink = el("a", "", "查看來源影片"); sourceLink.href = job.source_url; sourceLink.target = "_blank"; sourceLink.rel = "noopener noreferrer"; fragment.append(sourceLink);
  if (job.mode === "separate") fragment.append(el("p", "detail-meta", exportSummary(job)));
  if (canOpenResultFolder(job)) {
    const actions = el("div", "job-actions"); actions.append(resultFolderButton(job)); fragment.append(actions);
  }
  if (!job.artifacts.length) fragment.append(el("p", "detail-meta", "目前尚無已發布檔案。"));
  for (const artifact of job.artifacts) {
    const box = el("div", "artifact"), title = el("div", "artifact-title");
    title.append(el("strong", "", kinds[artifact.kind] || artifact.kind));
    if (artifact.available) {
      const a = el("a", "", "下載 · " + size(artifact.size)); a.href = artifact.url + "?download=true"; title.append(a); box.append(title);
      if (artifact.media_type.startsWith("audio/")) { const audio = el("audio"); audio.controls = true; audio.preload = "none"; audio.src = artifact.url; box.append(audio); }
    } else { title.append(el("span", "job-error", "檔案遺失或大小異常")); box.append(title); }
    fragment.append(box);
  }
  fragment.append(el("h3", "", "執行紀錄"));
  const events = el("ul", "events");
  for (const event of job.events) events.append(el("li", "", date(event.time) + " · " + event.message));
  fragment.append(events); $("#job-detail").replaceChildren(fragment);
  if (!$("#job-dialog").open) $("#job-dialog").showModal();
}
async function refresh(force = false) {
  if (state.busy) return; state.busy = true;
  try {
    await capabilities();
    const query = new URLSearchParams({ limit: String(state.limit), offset: String(state.offset) });
    if ($("#filter").value) query.set("state", $("#filter").value);
    const data = await api("/api/jobs?" + query);
    $("#count-queued").textContent = data.counts.queued || 0;
    $("#count-running").textContent = (data.counts.running || 0) + (data.counts.publishing || 0) + (data.counts.recovering || 0);
    $("#count-completed").textContent = data.counts.completed || 0;
    $("#result-count").textContent = data.total + " 筆工作";
    const signature = JSON.stringify(data);
    if (force || state.signature !== signature) {
      state.signature = signature;
      if (data.items.length) $("#jobs").replaceChildren(...data.items.map(renderJob));
      else { const empty = el("div", "empty"); empty.append(el("div", "empty-symbol", "≋"), el("h3", "", data.total ? "這一頁沒有工作。" : "你的下一首，從這裡開始。"), el("p", "", "貼上網址建立工作，或切換篩選查看紀錄。")); $("#jobs").replaceChildren(empty); }
    }
    $("#previous").disabled = state.offset === 0; $("#next").disabled = state.offset + state.limit >= data.total;
    $("#page-label").textContent = "第 " + (state.offset / state.limit + 1) + " 頁";
    $("#queue-error").hidden = true;
  } catch (error) { $("#queue-error").textContent = "無法更新工作室：" + error.message; $("#queue-error").hidden = false; }
  finally { state.busy = false; }
}
$("#job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const urls = $("#urls").value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  if (!urls.length || urls.length > 20) { toast("請輸入 1 至 20 筆網址。"); return; }
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const payload = { urls, mode, extra_exports: mode === "separate" ? selectedExports() : [], execution_kind: $("#demo").checked ? "demo" : "real" };
  if (!$("#model-options").hidden) payload.model_preset = $("#model-preset").value;
  const fingerprint = JSON.stringify(payload);
  if (state.fingerprint !== fingerprint || !state.key) { state.fingerprint = fingerprint; state.key = crypto.randomUUID(); }
  $("#submit").disabled = true;
  try {
    const result = await api("/api/jobs/batch", { method: "POST", body: JSON.stringify({ ...payload, idempotency_key: state.key }) });
    $("#submission").textContent = "已加入 " + result.items.filter(i => i.job_id).length + " 筆工作。" + result.items.filter(i => i.error).map(i => "\n第 " + (i.index + 1) + " 行：" + i.error.message).join("");
    state.key = null; $("#urls").value = ""; updateCount(); state.offset = 0; await refresh(true);
  } catch (error) { $("#submission").textContent = error.body?.items ? error.body.items.map(i => "第 " + (i.index + 1) + " 行：" + i.error.message).join("\n") : error.message; }
  finally { $("#submit").disabled = false; }
});
function updateCount() { $("#url-count").textContent = $("#urls").value.split(/\r?\n/).filter(s => s.trim()).length + " 筆網址"; }
$("#urls").addEventListener("input", updateCount);
$("#example").addEventListener("click", () => { $("#urls").value = "https://youtu.be/EXAMPLE0001\nhttps://www.youtube.com/watch?v=EXAMPLE0002"; $("#demo").checked = true; document.querySelector('input[value="separate"]').checked = true; updateCount(); executionNote(); });
for (const radio of document.querySelectorAll('input[name="mode"]')) radio.addEventListener("change", executionNote);
$("#demo").addEventListener("change", executionNote);
$("#model-preset").addEventListener("change", showModelPreset);
$("#filter").addEventListener("change", () => { state.offset = 0; refresh(true); });
$("#refresh").addEventListener("click", () => refresh(true));
$("#previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); refresh(true); });
$("#next").addEventListener("click", () => { state.offset += state.limit; refresh(true); });
$("#close-dialog").addEventListener("click", () => { $("#job-dialog").close(); state.dialogJob = null; });
refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 2500);
