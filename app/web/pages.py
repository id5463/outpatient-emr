"""页面。单文件，无外部依赖，方便直接对外广播演示。"""

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>门诊病历填写系统</title>
<style>
  :root { --fg:#1a1a1a; --muted:#666; --line:#e2e2e2; --bg:#fafafa; --accent:#2563eb; }
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif;
         color:var(--fg); background:var(--bg); line-height:1.6; }
  header { padding:20px 28px; border-bottom:1px solid var(--line); background:#fff; }
  h1 { margin:0; font-size:18px; font-weight:600; }
  .sub { color:var(--muted); font-size:13px; margin-top:4px; }
  main { display:grid; grid-template-columns:minmax(320px,1fr) minmax(360px,1.2fr);
         gap:0; height:calc(100vh - 76px); }
  section { padding:20px 24px; overflow:auto; }
  section + section { border-left:1px solid var(--line); background:#fff; }
  label { display:block; font-size:13px; color:var(--muted); margin:12px 0 4px; }
  textarea, input[type=text] { width:100%; padding:10px; border:1px solid var(--line);
    border-radius:6px; font-family:inherit; font-size:14px; background:#fff; }
  textarea { min-height:220px; resize:vertical; }
  .row { display:flex; gap:12px; }
  .row > div { flex:1; }
  button { margin-top:14px; padding:10px 18px; border:0; border-radius:6px;
    background:var(--accent); color:#fff; font-size:14px; cursor:pointer; }
  button:disabled { opacity:.55; cursor:not-allowed; }
  button.ghost { background:#fff; color:var(--fg); border:1px solid var(--line); }
  .tabs { display:flex; gap:8px; margin-bottom:8px; }
  .tabs button { margin:0; padding:6px 14px; font-size:13px; background:#fff;
    color:var(--muted); border:1px solid var(--line); }
  .tabs button.on { background:var(--accent); color:#fff; border-color:var(--accent); }
  .meta { font-size:12px; color:var(--muted); margin-top:12px; white-space:pre-wrap; }
  pre { white-space:pre-wrap; word-break:break-word; font-family:inherit; font-size:14px;
        background:#fff; border:1px solid var(--line); border-radius:6px;
        padding:16px; margin:0; }
  .hidden { display:none !important; }
  .err { color:#b91c1c; font-size:13px; margin-top:10px; white-space:pre-wrap; }
  .badge { display:inline-block; padding:1px 8px; border-radius:10px; font-size:12px;
    background:#eef2ff; color:#3730a3; margin-right:6px; }
  .recrow { display:flex; align-items:center; gap:12px; margin-top:6px; }
  button.rec { margin:0; background:#dc2626; }
  button.rec.on { background:#111; }
  .reclabel { font-size:13px; color:var(--muted); }
  .timer { font-variant-numeric:tabular-nums; font-size:26px; margin:8px 0;
    color:#111; letter-spacing:1px; }
  audio { width:100%; margin-top:6px; }
  .hintbox { font-size:12px; color:var(--muted); background:#f6f7f9;
    border:1px solid var(--line); border-radius:6px; padding:10px; margin-top:12px; }
</style>
</head>
<body>
<header>
  <h1>门诊病历填写系统</h1>
  <div class="sub">对话 → 结构化字段 → 门诊病历 Markdown · 判断模型 + 大语言模型 + ASR</div>
</header>
<main>
  <section>
    <div class="tabs">
      <button id="tab-rec" class="on">直接录音</button>
      <button id="tab-audio">上传音频</button>
      <button id="tab-text">粘贴对话</button>
    </div>

    <div id="pane-rec">
      <label>问诊录音</label>
      <div class="recrow">
        <button id="rec-btn" class="rec">开始录音</button>
        <span id="rec-state" class="reclabel">未开始</span>
      </div>
      <div id="rec-timer" class="timer">00:00</div>
      <audio id="rec-play" controls class="hidden"></audio>
      <div class="hintbox" id="rec-hint">
        直接对着麦克风录问诊过程。录完点「停止」，再点下面的「生成病历」。
      </div>
    </div>

    <div id="pane-text" class="hidden">
      <label>对话内容（每行「角色：内容」）</label>
      <textarea id="transcript">医生：你好，请坐。今天哪里不舒服？
患者：最近经常肚子痛，吃完饭以后更胀。
医生：痛了多久了？
患者：大概一个星期，有时候还恶心。
医生：以前有胃病吗？
患者：没有胃病，最近总吃辣的，也不太按时吃饭。</textarea>
    </div>

    <div id="pane-audio" class="hidden">
      <label>已有音频文件（wav / mp3 / m4a / webm）</label>
      <input type="file" id="audio" accept=".wav,.mp3,.m4a,.webm,.ogg,.flac,.amr">
      <label>说话人数</label>
      <input type="text" id="speakers" value="2">
    </div>

    <div class="row">
      <div><label>就诊时间</label><input type="text" id="visited" placeholder="留空则不填"></div>
    </div>

    <button id="go">生成病历</button>
    <button id="copy" class="ghost">复制 Markdown</button>
    <div class="meta" id="meta"></div>
    <div class="err" id="err"></div>
  </section>

  <section>
    <label>生成结果</label>
    <pre id="out">尚未生成。</pre>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
let mode = "rec";
let lastMarkdown = "";

$("tab-rec").onclick = () => setMode("rec");
$("tab-text").onclick = () => setMode("text");
$("tab-audio").onclick = () => setMode("audio");
function setMode(m) {
  mode = m;
  for (const k of ["rec", "audio", "text"]) {
    $("tab-" + k).classList.toggle("on", m === k);
    $("pane-" + k).classList.toggle("hidden", m !== k);
  }
}

// ---- 直接录音 ----
let recorder = null, chunks = [], recStart = 0, timerId = null, recordedBlob = null;

// 浏览器只在安全上下文里暴露 getUserMedia。检测到不是安全上下文时
// 直接把「直接录音」降级为不可用，并给出三条真正能走的路径。
const secure = window.isSecureContext === true &&
               !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

function initRecorder() {
  if (secure) return;
  $("rec-btn").disabled = true;
  $("rec-btn").textContent = "录音不可用";
  $("rec-state").textContent = "当前不是安全上下文";
  $("rec-timer").textContent = "--:--";
  $("rec-hint").innerHTML =
    "<b>浏览器只在 https 或 localhost 下允许录音。</b>" +
    "当前是 <code>" + location.protocol + "//" + location.host + "</code>。" +
    "任选一种方式：<br>" +
    "1. <b>用 SSH 隧道</b>（最省事，麦克风可用）：<br>" +
    "<code>ssh -L 8084:127.0.0.1:8085 ubuntu@111.229.224.168</code><br>" +
    "然后打开 <code>http://127.0.0.1:8084/</code><br>" +
    "2. <b>手机先录好音频</b>，用「上传音频」页签提交。<br>" +
    "3. 给本站配 HTTPS 证书后直接录音。";
  // 默认落到上传页签，避免用户卡在一个用不了的功能上
  setMode("audio");
}
document.addEventListener("DOMContentLoaded", initRecorder);

$("rec-btn").onclick = async () => {
  if (!secure) { initRecorder(); return; }
  if (recorder && recorder.state === "recording") { stopRecording(); return; }
  $("err").textContent = "";
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $("err").textContent = "当前环境不支持录音。请用 SSH 隧道访问 localhost。";
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    chunks = [];
    const mime = pickMime();
    recorder = mime ? new MediaRecorder(stream, { mimeType: mime })
                    : new MediaRecorder(stream);
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      recordedBlob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      const url = URL.createObjectURL(recordedBlob);
      $("rec-play").src = url;
      $("rec-play").classList.remove("hidden");
      $("rec-state").textContent = `已录 ${fmt(elapsed())}，${(recordedBlob.size/1024/1024).toFixed(2)} MB`;
    };
    recorder.start(1000);
    recStart = Date.now();
    $("rec-btn").textContent = "停止录音";
    $("rec-btn").classList.add("on");
    $("rec-state").textContent = "录音中…";
    $("rec-play").classList.add("hidden");
    timerId = setInterval(() => { $("rec-timer").textContent = fmt(elapsed()); }, 500);
  } catch (e) {
    $("err").textContent = "无法打开麦克风：" + (e.message || e);
  }
};

function stopRecording() {
  if (recorder && recorder.state === "recording") recorder.stop();
  clearInterval(timerId);
  $("rec-btn").textContent = "重新录音";
  $("rec-btn").classList.remove("on");
}
function elapsed() { return Math.floor((Date.now() - recStart) / 1000); }
function fmt(s) {
  const m = String(Math.floor(s / 60)).padStart(2, "0");
  return m + ":" + String(s % 60).padStart(2, "0");
}
function pickMime() {
  const cands = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  for (const c of cands) if (window.MediaRecorder && MediaRecorder.isTypeSupported(c)) return c;
  return "";
}

$("go").onclick = async () => {
  $("err").textContent = "";
  $("meta").textContent = "";
  $("out").textContent = "生成中…";
  $("go").disabled = true;
  const t0 = Date.now();
  try {
    let res, data;
    if (mode === "text") {
      res = await fetch("/api/record/text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcript: $("transcript").value,
          visited_at: $("visited").value || null,
          persist: true,
        }),
      });
    } else if (mode === "rec") {
      if (!recordedBlob) { throw new Error("请先录一段音频"); }
      const ext = (recordedBlob.type || "").includes("mp4") ? "m4a" : "webm";
      const fd = new FormData();
      fd.append("file", recordedBlob, "recording." + ext);
      fd.append("speakers", "2");
      fd.append("persist", "true");
      res = await fetch("/api/record/audio", { method: "POST", body: fd });
    } else {
      const f = $("audio").files[0];
      if (!f) { throw new Error("请选择音频文件"); }
      const fd = new FormData();
      fd.append("file", f);
      fd.append("speakers", $("speakers").value || "2");
      fd.append("persist", "true");
      res = await fetch("/api/record/audio", { method: "POST", body: fd });
    }
    data = await res.json();
    if (!res.ok) { throw new Error(data.detail || ("HTTP " + res.status)); }
    lastMarkdown = data.markdown || "";
    $("out").textContent = lastMarkdown || "（空）";
    const d = data.closed || {};
    const bits = Object.entries(d)
      .filter(([, v]) => v && typeof v === "object")
      .map(([k, v]) => `${k}=${v.label ?? v.value}${v.uncertain ? "(?)" : ""}`)
      .join("  ");
    $("meta").textContent =
      `耗时 ${((Date.now() - t0) / 1000).toFixed(1)}s\\n` +
      `模型 ${JSON.stringify(data.models_used)}\\n` +
      `判断 ${bits || "无"}\\n` +
      `文件 ${data.files ? JSON.stringify(data.files) : "(见服务端 out/)"}` +
      (data.warnings && data.warnings.length ? `\\n提示 ${data.warnings.join(" | ")}` : "");
  } catch (e) {
    $("out").textContent = "生成失败。";
    $("err").textContent = String(e.message || e);
  } finally {
    $("go").disabled = false;
  }
};

$("copy").onclick = async () => {
  if (!lastMarkdown) return;
  try { await navigator.clipboard.writeText(lastMarkdown); $("copy").textContent = "已复制"; }
  catch { $("copy").textContent = "复制失败"; }
  setTimeout(() => ($("copy").textContent = "复制 Markdown"), 1500);
};
</script>
</body>
</html>
"""
