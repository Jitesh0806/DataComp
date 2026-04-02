/* ═══════════════════════════════════════════════
   DataComp — Video Compression Engine
   Frontend Engine
   ═══════════════════════════════════════════════ */
"use strict";

const API = "";
const $ = id => document.getElementById(id);

// ── State ──────────────────────────────────────
let currentJobId  = null;
let pollTimer     = null;
let currentFrames = [];
let selectedFile  = null;
let activeTab     = "compare";

// ── Clock ──────────────────────────────────────
(function tickClock() {
  const el = $("footClock");
  if (el) el.textContent = new Date().toTimeString().slice(0, 8);
  setTimeout(tickClock, 1000);
})();

// ── Tab Navigation ─────────────────────────────
window.switchTab = function(el) {
  const tab = el.dataset.tab;
  document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));
  el.classList.add("active");
  activeTab = tab;
  document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
  const pane = $("tab-" + tab);
  if (pane) pane.classList.add("active");
  if (tab === "diff") drawDiffMap();
};

// ── Sliders ────────────────────────────────────
function initSlider(sliderId, valId, suffix) {
  const s = $(sliderId), v = $(valId);
  if (!s || !v) return;
  s.addEventListener("input", () => {
    v.innerHTML = s.value + (suffix || "");
  });
}
initSlider("p-qp",  "v-qp");
initSlider("p-gop", "v-gop");
initSlider("p-sr",  "v-sr");
initSlider("p-br",  "v-br", ' <em>kbps</em>');

// ── Toggles ────────────────────────────────────
document.querySelectorAll(".tog").forEach(tog => {
  tog.addEventListener("click", () => {
    tog.classList.toggle("on");
    const name = tog.id.replace("t-", "").toUpperCase();
    addLog(`${name}: ${tog.classList.contains("on") ? "enabled" : "disabled"}`);
  });
});

// ── Drop Zone ──────────────────────────────────
const dropZone = $("dropZone");
const fileInput = $("fileInput");

if (dropZone) {
  dropZone.addEventListener("dragover", e => { e.preventDefault(); dropZone.classList.add("dragover"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", e => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    const f = e.dataTransfer.files[0];
    if (f) handleFileSelect(f);
  });
  dropZone.addEventListener("click", () => fileInput.click());
}
if (fileInput) {
  fileInput.addEventListener("change", e => { if (e.target.files[0]) handleFileSelect(e.target.files[0]); });
}

function handleFileSelect(file) {
  selectedFile = file;
  const sizeMB = (file.size / 1024 / 1024).toFixed(2);
  const dzInfo = $("dz-info");
  dzInfo.style.display = "block";
  dzInfo.textContent = `${file.name}  ·  ${sizeMB} MB`;
  $("infoOrig").textContent = sizeMB + " MB";

  // Preview frame on original canvas
  const url = URL.createObjectURL(file);
  const vid = document.createElement("video");
  vid.src = url; vid.muted = true;
  vid.addEventListener("loadeddata", () => { vid.currentTime = 0.5; });
  vid.addEventListener("seeked", () => {
    const c = $("canvasOrig");
    const ctx = c.getContext("2d");
    const aspect = vid.videoWidth / vid.videoHeight;
    c.width = 960; c.height = Math.round(960 / aspect);
    ctx.drawImage(vid, 0, 0, c.width, c.height);
    const emptyEl = $("emptyOrig");
    if (emptyEl) emptyEl.style.display = "none";
    URL.revokeObjectURL(url);
  }, { once: true });

  addLog(`Loaded: ${file.name}  (${sizeMB} MB)`, "ok");
  setStatus("READY", "active");
}

// ── Status & Log ───────────────────────────────
function setStatus(text, dotClass) {
  $("sys-status").textContent = text;
  const dot = $("sdot");
  dot.className = "status-dot" + (dotClass ? " " + dotClass : "");
}

function addLog(msg, type) {
  const logBody = $("logBody");
  if (!logBody) return;
  const ts = new Date().toTimeString().slice(0, 8);
  const entry = document.createElement("div");
  entry.className = "log-entry" + (type ? " " + type : "");
  entry.innerHTML = `<span class="log-ts">${ts}</span><span class="log-msg">${msg}</span>`;
  logBody.appendChild(entry);
  logBody.scrollTop = logBody.scrollHeight;
}

// ── Encode ─────────────────────────────────────
window.startEncode = async function() {
  if (!selectedFile) { addLog("No source file selected.", "err"); return; }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

  const btn = $("encodeBtn");
  btn.disabled = true;
  btn.innerHTML = `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="10" cy="10" r="8"/><path d="M10 6v4l3 2"/></svg> Processing…`;
  $("progressWrap").style.display = "block";
  $("progFill").style.width = "0%";
  $("progPct").textContent = "0%";
  $("progStage").textContent = "Uploading";
  setStatus("ENCODING", "busy");

  const fd = new FormData();
  fd.append("video",                   selectedFile);
  fd.append("qp",                      $("p-qp").value);
  fd.append("gop_size",                $("p-gop").value);
  fd.append("search_range",            $("p-sr").value);
  fd.append("target_bitrate_kbps",     $("p-br").value);
  fd.append("block_size",              $("p-mb").value);
  fd.append("entropy_mode",            $("p-ent").value);
  fd.append("adaptive_quantization",   $("t-aq").classList.contains("on"));
  fd.append("scene_change_detection",  $("t-sc").classList.contains("on"));
  fd.append("rate_control",            $("t-rc").classList.contains("on"));
  fd.append("deblocking",              $("t-db").classList.contains("on"));

  try {
    const res = await fetch(`${API}/api/upload`, { method: "POST", body: fd });
    if (!res.ok) throw new Error(`Upload failed (${res.status})`);
    const data = await res.json();
    currentJobId = data.job_id;
    addLog(`Job ${currentJobId.slice(0, 8)}… started`, "info");
    startPolling();
  } catch(e) {
    addLog(`Error: ${e.message}`, "err");
    resetBtn();
    setStatus("ERROR");
  }
};

function resetBtn() {
  const btn = $("encodeBtn");
  btn.disabled = false;
  btn.innerHTML = `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 3l11 7-11 7V3z"/></svg> Run Compression`;
}

// ── Polling ────────────────────────────────────
function startPolling() {
  pollTimer = setInterval(async () => {
    if (!currentJobId) return;
    try {
      const res = await fetch(`${API}/api/jobs/${currentJobId}`);
      if (!res.ok) return;
      const job = await res.json();

      const pct = Math.round(job.progress || 0);
      $("progFill").style.width = pct + "%";
      $("progPct").textContent = pct + "%";
      $("progStage").textContent = (job.stage || "Processing").charAt(0).toUpperCase() + (job.stage || "Processing").slice(1);

      if (job.log && job.log.length > 0) {
        const current = $("logBody").querySelectorAll(".log-entry").length - 4;
        if (job.log.length > current) {
          job.log.slice(current < 0 ? 0 : current).forEach(l => addLog(l.msg, l.type));
        }
      }

      if (job.status === "done") {
        clearInterval(pollTimer); pollTimer = null;
        setStatus("DONE", "active");
        resetBtn();
        if (job.result) renderResults(job.result);
        addLog("Compression complete.", "ok");
      }
      if (job.status === "error") {
        clearInterval(pollTimer); pollTimer = null;
        addLog(`Engine error: ${job.error}`, "err");
        setStatus("ERROR");
        resetBtn();
      }
    } catch(e) { /* silent */ }
  }, 1000);
}

// ── Render Results ─────────────────────────────
function renderResults(res) {
  const m = res.metrics;

  // Animate metric values
  animCount("mc-ratio", m.compression_ratio, 2, "×");
  animCount("mc-psnr",  m.psnr_db, 2, " dB");
  animCount("mc-ssim",  m.ssim, 4, "");
  animCount("mc-fps",   m.encoding_fps, 1, " fps");

  $("mc-if").textContent = m.i_frames;
  $("mc-pf").textContent = m.p_frames;
  $("mc-sc").textContent = m.scene_changes;
  $("mc-bits").textContent = (m.total_bits / 1024).toFixed(1) + " KB";
  $("mc-mv").textContent = m.avg_mv_displacement + " px";
  $("mc-time").textContent = m.encoding_time_s + "s";

  // Quality badge
  const qEl = $("mc-quality");
  if (m.psnr_db > 38)      { qEl.textContent = "Excellent quality"; qEl.style.color = "var(--green)"; }
  else if (m.psnr_db > 32) { qEl.textContent = "High quality"; qEl.style.color = "var(--accent)"; }
  else if (m.psnr_db > 26) { qEl.textContent = "Medium quality"; qEl.style.color = "var(--orange)"; }
  else                      { qEl.textContent = "Low quality"; qEl.style.color = "var(--red)"; }

  // Progress bars
  setTimeout(() => {
    $("mb-ratio").style.width = Math.min(m.compression_ratio * 6, 100) + "%";
    $("mb-psnr").style.width  = Math.min(m.psnr_db * 2, 100) + "%";
    $("mb-ssim").style.width  = (m.ssim * 100) + "%";
    $("mb-fps").style.width   = Math.min(m.encoding_fps * 2, 100) + "%";
  }, 50);

  $("infoComp").textContent = "PSNR: " + m.psnr_db.toFixed(2) + " dB  ·  SSIM: " + m.ssim.toFixed(4);

  // Load compressed frame
  const comp = $("canvasComp");
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.src = `${API}/api/frame/${currentJobId}/compressed?t=${Date.now()}`;
  img.onload = () => {
    const ctx = comp.getContext("2d");
    comp.width = img.naturalWidth;
    comp.height = img.naturalHeight;
    ctx.drawImage(img, 0, 0);
    const emptyEl = $("emptyComp");
    if (emptyEl) emptyEl.style.display = "none";
    drawDiffMap();
  };

  // Charts
  currentFrames = res.frame_data;
  renderDCT("miniDct", res.dct_sample, true);
  drawBitstream(currentFrames);
  renderFrameStats(currentFrames);
  renderFrameList(currentFrames);

  // Download
  $("dl-card").style.display = "block";
  $("dlBtn").href = `${API}/api/download/${currentJobId}`;

  // Hide bitstream placeholder
  const bsPh = $("bs-ph");
  if (bsPh) bsPh.style.display = "none";
}

function animCount(id, target, dec, suffix) {
  const el = $(id);
  if (!el) return;
  const dur = 1000;
  const start = Date.now();
  function tick() {
    const p = Math.min((Date.now() - start) / dur, 1);
    const ease = 1 - Math.pow(1 - p, 3);
    el.textContent = (target * ease).toFixed(dec) + suffix;
    if (p < 1) requestAnimationFrame(tick);
  }
  tick();
}

// ── DCT Visualizer ─────────────────────────────
function renderDCT(id, coeffs, mini) {
  const el = $(id);
  if (!el) return;
  el.innerHTML = "";
  const maxVal = Math.max(...coeffs.map(Math.abs), 1);
  coeffs.forEach(v => {
    const cell = document.createElement("div");
    cell.className = "dc";
    const alpha = Math.abs(v) / maxVal;
    if (v > 0) cell.style.background = `rgba(200,255,0,${0.08 + alpha * 0.7})`;
    else if (v < 0) cell.style.background = `rgba(77,184,255,${0.08 + alpha * 0.7})`;
    else cell.style.background = "rgba(255,255,255,0.04)";
    el.appendChild(cell);
  });
}

// ── Bitstream Chart ────────────────────────────
function drawBitstream(frames) {
  const c = $("canvasBitstream");
  if (!c || !frames.length) return;
  const dpr = window.devicePixelRatio || 1;
  c.width  = c.offsetWidth  * dpr;
  c.height = c.offsetHeight * dpr;
  const ctx = c.getContext("2d");
  ctx.scale(dpr, dpr);
  const W = c.offsetWidth, H = c.offsetHeight;

  ctx.clearRect(0, 0, W, H);
  const maxBits = Math.max(...frames.map(f => f.bits), 1);
  const bw = W / frames.length;

  frames.forEach((f, i) => {
    const bh = ((f.bits / maxBits) * (H - 8));
    if (f.type === "S") ctx.fillStyle = "rgba(255,209,102,0.9)";
    else if (f.type === "I") ctx.fillStyle = "rgba(255,147,64,0.85)";
    else ctx.fillStyle = "rgba(200,255,0,0.6)";
    ctx.fillRect(i * bw + 0.5, H - bh, Math.max(bw - 1, 1), bh);
  });
}

// ── Frame Stats Chart ──────────────────────────
function renderFrameStats(frames) {
  const c = $("canvasFrameStats");
  if (!c || !frames.length) return;
  const dpr = window.devicePixelRatio || 1;
  c.width  = c.offsetWidth  * dpr;
  c.height = c.offsetHeight * dpr;
  const ctx = c.getContext("2d");
  ctx.scale(dpr, dpr);
  const W = c.offsetWidth, H = c.offsetHeight;

  ctx.clearRect(0, 0, W, H);

  // Grid lines
  ctx.strokeStyle = "rgba(255,255,255,0.05)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const y = (H / 4) * i;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }

  // PSNR line
  const maxP = Math.max(...frames.map(f => f.psnr), 1);
  const minP = Math.min(...frames.map(f => f.psnr));
  const range = maxP - minP || 1;

  ctx.strokeStyle = "rgba(61,220,132,0.9)";
  ctx.lineWidth = 1.5;
  ctx.lineJoin = "round";
  ctx.beginPath();
  frames.forEach((f, i) => {
    const x = (i / (frames.length - 1 || 1)) * W;
    const y = H - 12 - ((f.psnr - minP) / range) * (H - 24);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Bit cost bars (subtle)
  const maxBits = Math.max(...frames.map(f => f.bits), 1);
  frames.forEach((f, i) => {
    const x = (i / (frames.length - 1 || 1)) * W;
    const bh = (f.bits / maxBits) * 20;
    ctx.fillStyle = f.type === "I" || f.type === "S"
      ? "rgba(255,147,64,0.3)"
      : "rgba(200,255,0,0.15)";
    ctx.fillRect(x - 1, H - bh, 2, bh);
  });

  const empty = $("br-ph");
  if (empty) empty.style.display = "none";
}

// ── Diff Map ───────────────────────────────────
function drawDiffMap() {
  const orig = $("canvasOrig");
  const comp = $("canvasComp");
  const diff = $("canvasDiff");
  if (!orig.width || !comp.width) return;

  diff.width = orig.width; diff.height = orig.height;
  const oCtx = orig.getContext("2d");
  const cCtx = comp.getContext("2d");
  const dCtx = diff.getContext("2d");

  const oD = oCtx.getImageData(0, 0, orig.width, orig.height).data;
  const cD = cCtx.getImageData(0, 0, comp.width,  comp.height).data;
  const dImg = dCtx.createImageData(diff.width, diff.height);

  for (let i = 0; i < oD.length; i += 4) {
    const dv = (Math.abs(oD[i]-cD[i]) + Math.abs(oD[i+1]-cD[i+1]) + Math.abs(oD[i+2]-cD[i+2])) / 3;
    dImg.data[i]   = Math.min(dv * 4, 255);
    dImg.data[i+1] = Math.min(dv * 0.5, 80);
    dImg.data[i+2] = Math.min(dv * 0.2, 40);
    dImg.data[i+3] = 255;
  }
  dCtx.putImageData(dImg, 0, 0);
}

// ── Frame List ─────────────────────────────────
function renderFrameList(frames) {
  const el = $("frameList");
  if (!el) return;
  el.innerHTML = "";
  frames.forEach(f => {
    const row = document.createElement("div");
    row.className = "fl-row";
    row.innerHTML =
      `<span class="fl-num">#${String(f.index).padStart(3, "0")}</span>` +
      `<span class="fl-badge ${f.type}">${f.type}</span>` +
      `<span class="fl-sz">${f.size_bytes}B</span>` +
      `<span class="fl-bits">${f.psnr.toFixed(1)}dB</span>`;
    el.appendChild(row);
  });
}

// ── Health Check ───────────────────────────────
async function checkHealth() {
  try {
    const res = await fetch(`${API}/api/health`);
    if (res.ok) {
      const d = await res.json();
      addLog(`Engine v${d.version} online`, "ok");
    }
  } catch { addLog("Engine unreachable — start the backend server.", "err"); }
}

// ── Init ───────────────────────────────────────
checkHealth();
renderDCT("miniDct", Array(64).fill(0), true);
