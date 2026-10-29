"use strict";

/* ------------------------------------------------------------------ *
 * HawkTranscriber front-end (vanilla JS, no build step)
 * ------------------------------------------------------------------ */

const state = {
  view: "new",
  settings: null,
  system: null,
  models: [],
  recommendedModel: null,
  languages: [],
  formats: [],
  jobs: [],
  currentJob: null,
  pendingFile: null,
  inputMode: "file",
  socialPlatform: "youtube",
  socialUrl: "",
  socialFetching: false,
  socialProgressPct: 0,
  socialProgressDeterminate: false,
  options: {
    model: null,
    language: "auto",
    task: "transcribe",
    wordTimestamps: false,
    advanced: false,
  },
  transcript: {
    editing: false,
    query: "",
    follow: true,
    activeIndex: -1,
  },
  libraryFilter: "all",
  libraryQuery: "",
  poll: null,
  sidebarPoll: null,
  dirty: false,
};

const $ = (selector, root) => (root || document).querySelector(selector);
const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));
const viewRoot = $("#viewRoot");
const modalRoot = $("#modalRoot");
const toastStack = $("#toastStack");

const SOCIAL_PLATFORMS = [
  { id: "youtube", label: "YouTube", placeholder: "https://www.youtube.com/watch?v=…" },
  { id: "instagram", label: "Instagram", placeholder: "https://www.instagram.com/reel/…" },
  { id: "facebook", label: "Facebook", placeholder: "https://www.facebook.com/watch/?v=…" },
  { id: "tiktok", label: "TikTok", placeholder: "https://www.tiktok.com/@…/video/…" },
  { id: "x", label: "X", placeholder: "https://x.com/…/status/…" },
  { id: "vimeo", label: "Vimeo", placeholder: "https://vimeo.com/…" },
  { id: "soundcloud", label: "SoundCloud", placeholder: "https://soundcloud.com/…" },
];

/* ------------------------------------------------------------------ *
 * Utilities
 * ------------------------------------------------------------------ */
function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fmtDuration(seconds) {
  if (!seconds && seconds !== 0) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return (h ? h + ":" + mm : mm) + ":" + String(s).padStart(2, "0");
}

function fmtClock(seconds) {
  return fmtDuration(seconds);
}

function fmtBytes(bytes) {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return value.toFixed(value >= 10 || i === 0 ? 0 : 1) + " " + units[i];
}

function fmtDate(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const now = new Date();
  const diff = (now - date) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  if (diff < 604800) return Math.floor(diff / 86400) + "d ago";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function videoExt(name) {
  const ext = (name.split(".").pop() || "").toLowerCase();
  return ["mp4", "mov", "mkv", "webm", "avi", "m4v", "mpeg", "mpg"].includes(ext);
}

function languageLabel(code) {
  const found = state.languages.find((l) => l.code === code);
  if (found) return found.label;
  return code === "auto" ? "Auto-detected" : (code || "unknown").toUpperCase();
}

function modelLabel(name) {
  const found = state.models.find((m) => m.name === name);
  return found ? found.label : name;
}

function statusMeta(status) {
  const map = {
    completed: { label: "Completed", cls: "completed" },
    running: { label: "Transcribing", cls: "running" },
    loading: { label: "Loading model", cls: "loading" },
    queued: { label: "Queued", cls: "queued" },
    failed: { label: "Failed", cls: "failed" },
    cancelled: { label: "Cancelled", cls: "cancelled" },
    interrupted: { label: "Interrupted", cls: "interrupted" },
    saving: { label: "Saving", cls: "running" },
  };
  return map[status] || { label: status || "Unknown", cls: "" };
}

function statusBadge(status) {
  const meta = statusMeta(status);
  const live = ["running", "loading", "queued", "saving"].includes(status);
  return '<span class="badge ' + meta.cls + '"><i class="dot"></i>' + escapeHtml(meta.label) + "</span>";
}

function countWords(text) {
  const trimmed = (text || "").trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).length;
}

function transcriptText(segments) {
  return (segments || [])
    .map((s) => (s.text || "").trim())
    .filter(Boolean)
    .join(" ");
}

function highlight(text, query) {
  if (!query) return escapeHtml(text);
  const safe = escapeHtml(text);
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  try {
    return safe.replace(new RegExp("(" + escaped + ")", "ig"), "<mark>$1</mark>");
  } catch (err) {
    return safe;
  }
}

function icon(name, size) {
  const s = size || 18;
  const icons = {
    mic: '<path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3Z"/><path d="M5 12a7 7 0 0 0 14 0M12 19v3"/>',
    upload: '<path d="M12 16V4m0 0L7 9m5-5 5 5"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.1 0l2-2A5 5 0 0 0 12 3.9l-1.1 1.1"/><path d="M14 11a5 5 0 0 0-7.1 0l-2 2A5 5 0 0 0 12 20.1l1.1-1.1"/>',
    play: '<path d="M6 4l14 8-14 8V4Z"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    edit: '<path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3Z"/><path d="m13.5 6.5 3 3"/>',
    download: '<path d="M12 4v12m0 0-5-5m5 5 5-5"/><path d="M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2"/>',
    trash: '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0v12a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V7"/>',
    check: '<path d="m5 13 4 4L19 7"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    alert: '<path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    refresh: '<path d="M4 12a8 8 0 0 1 13.7-5.6L20 8M20 4v4h-4"/><path d="M20 12a8 8 0 0 1-13.7 5.6L4 16m0 4v-4h4"/>',
    save: '<path d="M5 5h11l3 3v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z"/><path d="M8 5v5h7V5M8 20v-5h8v5"/>',
  };
  return (
    '<svg viewBox="0 0 24 24" width="' + s + '" height="' + s +
    '" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">' +
    (icons[name] || "") + "</svg>"
  );
}

function platformIcon(platform) {
  const glyphs = { facebook: "f", x: "𝕏", tiktok: "♪", more: "↗" };
  if (glyphs[platform]) return '<span class="platform-glyph platform-' + platform + '" aria-hidden="true">' + glyphs[platform] + '</span>';
  const paths = {
    youtube: '<rect x="2.5" y="5" width="19" height="14" rx="4"/><path d="m10 9 5 3-5 3z"/>',
    instagram: '<rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="4"/><path d="M17.5 6.8h.01"/>',
    vimeo: '<path d="M21 7.2c-.1 2.8-2.1 6.6-6 11.5-2 2.6-3.8 3.9-5.2 3.9-.9 0-1.7-.8-2.4-2.5L5 13.2c-.9-3.4-1.8-3.2-2.9-.7L1 11c1.9-2.7 3.7-4.1 5.4-4.3 2.2-.2 3.5 1.3 4 4.6.6 3.5 1 5.3 1.6 5.3.4 0 1.1-1.1 2.1-3.2 1-2.2 1.5-3.8 1.6-4.9.1-1.9-.6-2.8-2.1-2.8-.7 0-1.4.2-2.1.5 1.4-4.4 4-6.5 7.7-6.3 2.7.1 4 1.9 3.9 5.3z"/>',
    soundcloud: '<path d="M3 14v4M6 11v7M9 8v10M12 6v12M15 9v9M18 12h1.5a2.5 2.5 0 0 1 0 5H18z"/>',
  };
  return '<svg class="platform-svg platform-' + platform + '" viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (paths[platform] || "") + '</svg>';
}

/* ------------------------------------------------------------------ *
 * Notifications, modals, busy
 * ------------------------------------------------------------------ */
function toast(message, type, title) {
  const node = document.createElement("div");
  node.className = "toast " + (type || "info");
  const iconName = type === "error" ? "alert" : type === "success" ? "check" : "info";
  node.innerHTML =
    '<span class="t-icon">' + icon(iconName, 18) + "</span>" +
    '<div class="t-body">' + (title ? "<strong>" + escapeHtml(title) + "</strong>" : "") +
    escapeHtml(message) + "</div>";
  toastStack.appendChild(node);
  setTimeout(() => {
    node.style.transition = "opacity 250ms, transform 250ms";
    node.style.opacity = "0";
    node.style.transform = "translateY(6px)";
    setTimeout(() => node.remove(), 260);
  }, type === "error" ? 6500 : 3800);
}

function busy(on) {
  // Avoid blocking the workspace; save/open/retry actions remain usable inline.
  return Boolean(on);
}

function closeModal() {
  modalRoot.hidden = true;
  modalRoot.innerHTML = "";
}

function confirmModal({ title, message, confirmLabel, danger }) {
  return new Promise((resolve) => {
    modalRoot.hidden = false;
    modalRoot.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
      '<div class="modal-head"><h3>' + escapeHtml(title) + "</h3></div>" +
      '<div class="modal-body">' + escapeHtml(message) + "</div>" +
      '<div class="modal-foot">' +
      '<button class="btn btn-ghost" data-act="cancel">Cancel</button>' +
      '<button class="btn ' + (danger ? "btn-danger" : "btn-primary") + '" data-act="ok">' +
      escapeHtml(confirmLabel || "Confirm") + "</button>" +
      "</div></div>";
    const done = (value) => {
      closeModal();
      resolve(value);
    };
    modalRoot.querySelector('[data-act="cancel"]').onclick = () => done(false);
    modalRoot.querySelector('[data-act="ok"]').onclick = () => done(true);
    modalRoot.onclick = (e) => {
      if (e.target === modalRoot) done(false);
    };
  });
}

function promptModal({ title, label, value, confirmLabel }) {
  return new Promise((resolve) => {
    modalRoot.hidden = false;
    modalRoot.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true">' +
      '<div class="modal-head"><h3>' + escapeHtml(title) + "</h3></div>" +
      '<div class="modal-body"><div class="field"><label>' + escapeHtml(label) +
      '</label><input type="text" id="modalInput" value="' + escapeHtml(value || "") + '" /></div></div>' +
      '<div class="modal-foot">' +
      '<button class="btn btn-ghost" data-act="cancel">Cancel</button>' +
      '<button class="btn btn-primary" data-act="ok">' + escapeHtml(confirmLabel || "Save") + "</button>" +
      "</div></div>";
    const input = $("#modalInput");
    input.focus();
    input.select();
    const done = (val) => {
      closeModal();
      resolve(val);
    };
    const accept = () => done(input.value.trim());
    modalRoot.querySelector('[data-act="cancel"]').onclick = () => done(null);
    modalRoot.querySelector('[data-act="ok"]').onclick = accept;
    input.onkeydown = (e) => {
      if (e.key === "Enter") accept();
      if (e.key === "Escape") done(null);
    };
    modalRoot.onclick = (e) => {
      if (e.target === modalRoot) done(null);
    };
  });
}

/* ------------------------------------------------------------------ *
 * API
 * ------------------------------------------------------------------ */
async function api(path, options) {
  const opts = Object.assign({ headers: {} }, options || {});
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), opts.timeout || (path.includes("/api/jobs") && opts.method === "POST" ? 300000 : 20000));
  opts.signal = controller.signal;
  let response;
  try {
    response = await fetch(path, opts);
  } catch (err) {
    if (err.name === "AbortError") throw new Error("The request timed out. Check that HawkTranscriber is still running, then try again.");
    throw err;
  } finally {
    clearTimeout(timeout);
  }
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (err) {
    data = { error: text };
  }
  if (!response.ok) {
    const message = (data && data.error) || "Request failed (" + response.status + ")";
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

/* ------------------------------------------------------------------ *
 * Theme
 * ------------------------------------------------------------------ */
function applyTheme(theme) {
  const resolved = theme === "system"
    ? (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")
    : theme;
  document.documentElement.setAttribute("data-theme", resolved);
}

/* ------------------------------------------------------------------ *
 * Bootstrapping
 * ------------------------------------------------------------------ */
async function init() {
  try {
    const [settings, system, models, languages, formats, jobs] = await Promise.all([
      api("/api/settings"),
      api("/api/system"),
      api("/api/models"),
      api("/api/languages"),
      api("/api/exports"),
      api("/api/jobs"),
    ]);
    state.settings = settings.settings;
    state.system = system;
    state.models = models.models;
    state.recommendedModel = models.recommended;
    state.languages = languages.languages;
    state.formats = formats.formats;
    state.jobs = jobs.jobs;
  } catch (err) {
    viewRoot.innerHTML =
      '<div class="alert error">' + icon("alert", 18) +
      "<div><strong>The app could not start</strong><br>" + escapeHtml(err.message) +
      "</div></div>";
    return;
  }

  applyTheme(state.settings.theme);
  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => {
    if (state.settings.theme === "system") applyTheme("system");
  });

  state.options.model = state.settings.default_model || state.recommendedModel;
  state.options.language = state.settings.default_language || "auto";
  state.options.task = state.settings.default_task || "transcribe";
  state.options.wordTimestamps = !!state.settings.word_timestamps;

  bindChrome();
  updateLibraryCount();
  updateProcessingIndicator();
  if (state.jobs.some((j) => isActiveStatus(j.status))) startSidebarPolling();
  setView("new");

  if (state.system.recoveredJobs) {
    toast(
      state.system.recoveredJobs + " unfinished job(s) were marked as interrupted.",
      "info",
      "Recovered after restart"
    );
  }
  const ffmpegWarning = (state.system.warnings || []).find((w) => w.includes("FFmpeg"));
  if (ffmpegWarning) toast(ffmpegWarning, "warning", "FFmpeg not detected");
}

function bindChrome() {
  $("#newButton").onclick = () => {
    state.pendingFile = null;
    state.currentJob = null;
    stopPolling();
    setView("new");
  };
  $$(".nav-item").forEach((item) => {
    item.onclick = () => {
      const view = item.dataset.view;
      if (view === "library") refreshLibrary();
      setView(view);
    };
  });
}

function setView(view) {
  state.view = view;
  $$(".nav-item").forEach((i) => i.classList.toggle("active", i.dataset.view === view));
  if (view === "library") {
    stopPolling();
    renderLibrary();
    maybePollLibrary();
  } else if (view === "settings") {
    stopPolling();
    renderSettings();
  } else if (view === "new") {
    stopPolling();
    renderNew();
  } else if (view === "job") {
    renderJob();
    if (state.currentJob && isActiveStatus(state.currentJob.status)) startJobPolling(state.currentJob.id);
  }
}

function updateProcessingIndicator() {
  const host = $("#processingIndicator");
  if (!host) return;
  const active = state.jobs.filter((job) => isActiveStatus(job.status));
  host.hidden = active.length === 0;
  if (!active.length) { host.innerHTML = ""; return; }
  const job = active[0];
  const phase = job.message || statusMeta(job.status).label;
  host.innerHTML = '<span class="processing-title"><i class="processing-dot"></i>' + active.length +
    ' job' + (active.length === 1 ? '' : 's') + ' processing</span><span class="processing-detail">' +
    escapeHtml(job.title) + ' · ' + escapeHtml(phase) + (active.length > 1 ? ' · +' + (active.length - 1) + ' queued' : '') + '</span>';
}

function startSidebarPolling() {
  if (state.sidebarPoll) return;
  state.sidebarPoll = setInterval(async () => {
    await refreshJobs();
    if (!state.jobs.some((job) => isActiveStatus(job.status))) {
      clearInterval(state.sidebarPoll);
      state.sidebarPoll = null;
    }
  }, 1800);
}

/* ------------------------------------------------------------------ *
 * Polling
 * ------------------------------------------------------------------ */
function stopPolling() {
  if (state.poll) {
    clearInterval(state.poll);
    state.poll = null;
  }
}

function startJobPolling(jobId) {
  stopPolling();
  startSidebarPolling();
  state.poll = setInterval(async () => {
    try {
      const { job } = await api("/api/jobs/" + jobId);
      const wasActive = isActiveStatus(state.currentJob && state.currentJob.status);
      state.currentJob = job;
      state.jobs = state.jobs.map((item) => item.id === job.id ? Object.assign({}, item, job) : item);
      updateProcessingIndicator();
      if (state.view === "job") updateJobLive();
      if (isActiveStatus(job.status)) return;
      stopPolling();
      if (wasActive && job.status === "completed") {
        toast("Transcription complete.", "success", "Done");
        renderJob();
        refreshLibrary();
      } else if (wasActive && job.status === "failed") {
        renderJob();
        refreshLibrary();
      } else {
        renderJob();
      }
    } catch (err) {
      stopPolling();
    }
  }, 900);
}

function maybePollLibrary() {
  const hasActive = state.jobs.some((j) => isActiveStatus(j.status));
  if (!hasActive) return;
  stopPolling();
  state.poll = setInterval(async () => {
    try {
      await refreshLibrary();
      if (!state.jobs.some((j) => isActiveStatus(j.status))) stopPolling();
    } catch (err) {
      stopPolling();
    }
  }, 2500);
}

function isActiveStatus(status) {
  return ["queued", "loading", "running", "saving"].includes(status);
}

async function refreshLibrary() {
  return refreshJobs();
}

async function refreshJobs() {
  try {
    const { jobs } = await api("/api/jobs");
    state.jobs = jobs;
    updateLibraryCount();
    updateProcessingIndicator();
    if (state.view === "library") renderLibrary();
  } catch (err) {
    /* ignore */
  }
}

function updateLibraryCount() {
  const count = state.jobs.length;
  const badge = $("#libraryCount");
  badge.textContent = count;
  badge.hidden = count === 0;
}

/* ------------------------------------------------------------------ *
 * View: New transcription
 * ------------------------------------------------------------------ */
function renderNew() {
  const recent = state.jobs.filter((j) => j.status === "completed").slice(0, 4);
  viewRoot.innerHTML =
    '<header class="page-head">' +
    '<span class="eyebrow">' + icon("mic", 13) + "HawkTranscriber</span>" +
    "<h1>Transcribe a recording</h1>" +
    '<p class="lede">Choose a recording from this device or paste a public media link. Link media is fetched directly to this device; transcription stays local.</p>' +
    "</header>" +
    '<div id="newBody"></div>' +
    (recent.length
      ? '<div class="mt"><div class="row" style="justify-content:space-between;margin-bottom:12px">' +
        '<span class="section-title">Recent transcripts</span>' +
        '<button class="btn btn-ghost btn-sm" id="seeAll">View library</button></div>' +
        '<div class="list" id="recentList">' +
        recent.map((job) => libraryRow(job, true)).join("") +
        "</div></div>"
      : "") +
    '<input type="file" id="fileInput" class="hidden" accept="' +
    (state.system.supportedExtensions || []).join(",") + '" />';

  const seeAll = $("#seeAll");
  if (seeAll) seeAll.onclick = () => setView("library");
  bindLibraryRows($("#recentList"));
  renderNewBody();
}

function renderNewBody() {
  const body = $("#newBody");
  if (!body) return;

  const sourceSwitcher =
    '<div class="source-switcher" role="tablist" aria-label="Choose a media source">' +
    '<button type="button" class="source-tab ' + (state.inputMode === "file" ? "active" : "") + '" data-source="file" role="tab" aria-selected="' + (state.inputMode === "file") + '" ' + (state.socialFetching ? "disabled" : "") + '>' + icon("file", 17) + 'Upload a file</button>' +
    '<button type="button" class="source-tab ' + (state.inputMode === "link" ? "active" : "") + '" data-source="link" role="tab" aria-selected="' + (state.inputMode === "link") + '" ' + (state.socialFetching ? "disabled" : "") + '>' + icon("link", 17) + 'Social media link</button></div>';
  const bindSourceSwitcher = () => {
    $$("[data-source]", body).forEach((button) => {
      button.onclick = () => {
        state.inputMode = button.dataset.source;
        renderNewBody();
      };
    });
  };

  if (state.inputMode === "link") {
    const selected = SOCIAL_PLATFORMS.find((p) => p.id === state.socialPlatform) || SOCIAL_PLATFORMS[0];
    body.innerHTML = sourceSwitcher +
      '<form id="socialForm" class="stack social-form">' +
      '<div class="card card-pad"><div class="row wrap" style="justify-content:space-between;gap:8px;margin-bottom:14px"><div><div class="section-title">Choose a platform</div><div class="hint">Paste a public link from the matching site.</div></div><span class="social-local-note">Fetched to this device</span></div>' +
      '<div class="platform-grid" role="group" aria-label="Social media platform">' +
      SOCIAL_PLATFORMS.map((platform) => '<button type="button" class="platform-button ' + (state.socialPlatform === platform.id ? "active" : "") + '" data-platform="' + platform.id + '" aria-pressed="' + (state.socialPlatform === platform.id) + '" ' + (state.socialFetching ? "disabled" : "") + '>' + platformIcon(platform.id) + '<span>' + escapeHtml(platform.label) + '</span></button>').join("") +
      '</div><div class="field mt"><label for="socialUrl">' + escapeHtml(selected.label) + ' link</label>' +
      '<div class="social-url-row" style="display:flex;gap:8px;align-items:center"><div style="position:relative;flex:1"><input id="socialUrl" type="url" inputmode="url" autocomplete="url" placeholder="' + escapeHtml(selected.placeholder) + '" value="' + escapeHtml(state.socialUrl) + '" required ' + (state.socialFetching ? "disabled" : "") + ' style="padding-right:60px" />' +
      '<button class="btn btn-ghost" id="togglePasteClearBtn" type="button" ' + (state.socialFetching ? "disabled" : "") + ' style="position:absolute;right:4px;top:50%;transform:translateY(-50%);padding:4px 8px;min-width:auto;font-size:inherit">' + (state.socialUrl ? "Clear" : "Paste") + '</button></div>' +
      '<button class="btn btn-primary" id="fetchSocialBtn" type="submit" style="white-space:nowrap;' + (state.socialFetching ? "disabled" : "") + '>' + icon("download", 16) + '<span style="margin-left:6px">' + (state.socialFetching ? "Fetching…" : "Fetch & transcribe") + '</span></button></div>' +
      '<span class="hint">Public posts only. Private, login-required, age-restricted, or region-blocked media may not be available.</span></div></div>' +
      '<div id="socialProgress" class="social-progress" ' + (state.socialFetching ? "" : "hidden") + '><div class="progress' + (state.socialProgressDeterminate ? "" : " indeterminate") + '"><div class="bar" style="width:' + (state.socialProgressPct || 0) + '%"></div></div><span>' + (state.socialProgressDeterminate && state.socialProgressPct > 0 ? (state.socialProgressPct === 100 ? "Complete" : state.socialProgressPct + "% downloaded") : "Retrieving media from " + escapeHtml(selected.label) + "...") + '</span>' +
      (!state.socialProgressDeterminate ? '<button class="btn btn-ghost mt-2" id="cancelSocialBtn">Cancel</button>' : '') + '</div>' +
      '<div class="card card-pad"><span class="section-title">Transcription settings</span><div class="grid grid-2 mt" style="gap:14px">' + modelField() + languageField() + '</div>' +
      '<div class="divider mt"></div><div class="row wrap mt" style="gap:20px"><div class="field" style="min-width:220px"><label>Task</label><div class="segmented" id="taskSeg">' +
      '<button type="button" data-task="transcribe" class="' + (state.options.task === "transcribe" ? "active" : "") + '">Transcribe</button>' +
      '<button type="button" data-task="translate" class="' + (state.options.task === "translate" ? "active" : "") + '">Translate to English</button></div></div>' +
      '<label class="switch"><input type="checkbox" id="wordTs" ' + (state.options.wordTimestamps ? "checked" : "") + ' /><span class="track"></span><span class="switch-label">Word timestamps<small>More precise, slightly slower</small></span></label></div></div>' +
      '</form>';
    bindSourceSwitcher();
    $$("[data-platform]", body).forEach((button) => {
      button.onclick = () => {
        state.socialPlatform = button.dataset.platform;
        renderNewBody();
      };
    });
    $("#togglePasteClearBtn").onclick = () => {
      if (state.socialFetching) return;
      if (state.socialUrl) {
        state.socialUrl = "";
        $("#socialUrl").value = "";
      } else {
        navigator.clipboard.readText().then((text) => {
          $("#socialUrl").value = text;
          state.socialUrl = text;
          $("#togglePasteClearBtn").textContent = "Clear";
        }).catch((err) => {
          toast("Could not read from clipboard.", "error", "Clipboard error");
        });
        return;
      }
      $("#togglePasteClearBtn").textContent = "Paste";
    };
    $("#socialUrl").oninput = (event) => {
        state.socialUrl = event.target.value;
        $("#togglePasteClearBtn").textContent = state.socialUrl ? "Clear" : "Paste";
    };
    $("#cancelSocialBtn").onclick = async () => {
      if (!confirm("Cancel this download and transcription?")) return;
      const jobId = state.socialJobId || "current";
      try {
        await fetch(`/api/jobs/${jobId}/cancel-download`, { method: "POST" });
      } catch (err) {
        toast("Failed to cancel download.", "error", "Network error");
      }
      state.socialFetching = false;
      state.socialProgressPct = 0;
      state.socialProgressDeterminate = false;
      state.socialUrl = "";
      state.socialJobId = undefined;
      $("#togglePasteClearBtn").textContent = "Paste";
      $("#socialUrl").value = "";
      renderNewBody();
    };
    $("#modelSelect").onchange = (event) => { state.options.model = event.target.value; renderNewBody(); };
    $("#languageSelect").onchange = (event) => { state.options.language = event.target.value; };
    $$("#taskSeg button").forEach((button) => {
      button.onclick = () => {
        state.options.task = button.dataset.task;
        $$("#taskSeg button").forEach((item) => item.classList.toggle("active", item === button));
      };
    });
    $("#wordTs").onchange = (event) => { state.options.wordTimestamps = event.target.checked; };
    $("#socialForm").onsubmit = startSocialTranscription;
    return;
  }

  if (!state.pendingFile) {
    body.innerHTML =
      sourceSwitcher +
      '<div class="dropzone" id="dropzone">' +
      '<div class="dropzone-icon">' + icon("upload", 26) + "</div>" +
      "<h3>Drop a file here</h3>" +
      "<p>or click to browse. Your file is processed locally and never uploaded.</p>" +
      '<span class="formats">' + supportedFormatsLabel() + "</span>" +
      "</div>";
    const dropzone = $("#dropzone");
    dropzone.onclick = () => $("#fileInput").click();
    ["dragenter", "dragover"].forEach((evt) =>
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
      })
    );
    ["dragleave", "drop"].forEach((evt) =>
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
      })
    );
    dropzone.addEventListener("drop", (e) => {
      if (e.dataTransfer.files.length) acceptFile(e.dataTransfer.files[0]);
    });
    const input = $("#fileInput");
    input.value = "";
    input.onchange = () => {
      if (input.files.length) acceptFile(input.files[0]);
    };
    bindSourceSwitcher();
    return;
  }

  const file = state.pendingFile;
  body.innerHTML =
    sourceSwitcher + '<div class="stack">' +
    '<div class="file-chip">' +
    '<span class="file-icon">' + icon("file", 20) + "</span>" +
    '<div class="grow">' +
    '<div class="file-name">' + escapeHtml(file.name) + "</div>" +
    '<div class="file-meta">' + fmtBytes(file.size) + " · " + escapeHtml((file.name.split(".").pop() || "").toUpperCase()) + "</div>" +
    "</div>" +
    '<button class="btn btn-ghost btn-sm" id="changeFile">Change</button>' +
    "</div>" +
    '<div class="card card-pad">' +
    '<span class="section-title">Transcription settings</span>' +
    '<div class="grid grid-2 mt" style="gap:14px">' +
    modelField() +
    languageField() +
    "</div>" +
    '<div class="divider mt"></div>' +
    '<div class="row wrap mt" style="gap:20px">' +
    '<div class="field" style="min-width:220px"><label>Task</label>' +
    '<div class="segmented" id="taskSeg">' +
    '<button data-task="transcribe" class="' + (state.options.task === "transcribe" ? "active" : "") + '">Transcribe</button>' +
    '<button data-task="translate" class="' + (state.options.task === "translate" ? "active" : "") + '">Translate to English</button>' +
    "</div></div>" +
    '<label class="switch"><input type="checkbox" id="wordTs" ' + (state.options.wordTimestamps ? "checked" : "") + ' /><span class="track"></span>' +
    '<span class="switch-label">Word timestamps<small>More precise, slightly slower</small></span></label>' +
    "</div>" +
    "</div>" +
    '<div class="row" style="justify-content:flex-end;gap:10px">' +
    '<button class="btn btn-ghost" id="clearFile">Cancel</button>' +
    '<button class="btn btn-primary" id="startBtn">' + icon("play", 16) + "Start transcription</button>" +
    "</div>" +
    '<div id="uploadProgress"></div>' +
    "</div>";

  $("#changeFile").onclick = () => $("#fileInput").click();
  $("#clearFile").onclick = () => {
    state.pendingFile = null;
    renderNewBody();
  };
  const input = $("#fileInput");
  input.value = "";
  input.onchange = () => {
    if (input.files.length) acceptFile(input.files[0]);
  };
  $("#modelSelect").onchange = (e) => {
    state.options.model = e.target.value;
    renderNewBody();
  };
  $("#languageSelect").onchange = (e) => {
    state.options.language = e.target.value;
  };
  $$("#taskSeg button").forEach((btn) => {
    btn.onclick = () => {
      state.options.task = btn.dataset.task;
      $$("#taskSeg button").forEach((b) => b.classList.toggle("active", b === btn));
    };
  });
  $("#wordTs").onchange = (e) => {
    state.options.wordTimestamps = e.target.checked;
  };
  $("#startBtn").onclick = startTranscription;
  bindSourceSwitcher();
}

async function startSocialTranscription(event) {
  event.preventDefault();
  const input = $("#socialUrl");
  state.socialUrl = input.value.trim();
  if (!state.socialUrl) { input.focus(); return; }
  state.socialFetching = true;
  state.socialProgressPct = 0;
  state.socialProgressDeterminate = false;
  state.socialAbortCtrl = new AbortController();
  renderNewBody();
  try {
    const { job, warning } = await api("/api/jobs/from-url", {
      method: "POST",
      timeout: 30 * 60 * 1000,
      body: {
        url: state.socialUrl,
        platform: state.socialPlatform,
        model: state.options.model,
        language: state.options.language,
        task: state.options.task,
        word_timestamps: state.options.wordTimestamps,
      },
      signal: state.socialAbortCtrl.signal,
    });
    if (warning) toast(warning, "warning", "Heads up");
    state.currentJob = job;
    state.transcript = { editing: false, query: "", follow: true, activeIndex: -1 };
    setView("job");
    startJobPolling(job.id);
    refreshLibrary();
  } catch (err) {
    if (err.name !== "AbortError") {
      toast(err.message, "error", "Could not import this link");
    }
  } finally {
    state.socialFetching = false;
    state.socialProgressPct = 0;
    state.socialProgressDeterminate = false;
    if (state.socialAbortCtrl) state.socialAbortCtrl = null;
    if (state.view === "new" && state.inputMode === "link") renderNewBody();
  }
}

function supportedFormatsLabel() {
  const exts = (state.system.supportedExtensions || []).map((e) => e.replace(".", "").toUpperCase());
  const shown = exts.slice(0, 12).join(" · ");
  return "Supported: " + shown + (exts.length > 12 ? " · and more" : "");
}

function modelField() {
  const options = state.models
    .map((m) => {
      const tags = [];
      if (m.name === state.recommendedModel) tags.push("recommended");
      tags.push(m.downloaded ? "downloaded" : fmtBytes(m.sizeBytes));
      return (
        '<option value="' + m.name + '"' + (m.name === state.options.model ? " selected" : "") + ">" +
        escapeHtml(m.label + " — " + tags.join(", ")) + "</option>"
      );
    })
    .join("");
  const current = state.models.find((m) => m.name === state.options.model);
  let hint = "Model files live in a local cache folder.";
  if (current) {
    hint = current.multilingual ? "Multilingual" : "English-only";
    hint += " · " + current.relative_accuracy + " accuracy · needs ~" + current.approxMemoryGb + " GB RAM";
    if (!current.downloaded) hint += " · will download ~" + fmtBytes(current.sizeBytes);
  }
  return (
    '<div class="field"><label for="modelSelect">Model</label>' +
    '<select id="modelSelect">' + options + "</select>" +
    '<span class="hint">' + escapeHtml(hint) + "</span></div>"
  );
}

function languageField() {
  const options = state.languages
    .map(
      (l) =>
        '<option value="' + l.code + '"' + (l.code === state.options.language ? " selected" : "") + ">" +
        escapeHtml(l.label) + "</option>"
    )
    .join("");
  return (
    '<div class="field"><label for="languageSelect">Language</label>' +
    '<select id="languageSelect">' + options + "</select>" +
    '<span class="hint">Pick the spoken language, or let Whisper detect it.</span></div>'
  );
}

function acceptFile(file) {
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  const supported = (state.system.supportedExtensions || []).map((e) => e.replace(".", ""));
  if (!supported.includes(ext)) {
    toast("That file type is not supported. Try an audio or video file.", "error", "Unsupported format");
    return;
  }
  state.pendingFile = file;
  renderNewBody();
}

function startTranscription() {
  const file = state.pendingFile;
  if (!file) return;
  const startBtn = $("#startBtn");
  startBtn.disabled = true;

  const form = new FormData();
  form.append("file", file);
  form.append("model", state.options.model);
  form.append("language", state.options.language);
  form.append("task", state.options.task);
  form.append("word_timestamps", state.options.wordTimestamps ? "1" : "0");

  const progressHost = $("#uploadProgress");
  progressHost.innerHTML =
    '<div class="card card-pad mt"><div class="progress-wrap">' +
    '<div class="row" style="justify-content:space-between"><span class="section-title" id="upLabel">Uploading…</span><span class="faint" id="upPct">0%</span></div>' +
    '<div class="progress"><div class="bar" id="upBar" style="width:0%"></div></div></div></div>';

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/jobs");
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    const bar = $("#upBar");
    if (bar) bar.style.width = pct + "%";
    const pctEl = $("#upPct");
    if (pctEl) pctEl.textContent = pct + "%";
  };
  xhr.onload = () => {
    let data = {};
    try {
      data = JSON.parse(xhr.responseText || "{}");
    } catch (err) {
      data = {};
    }
    if (xhr.status >= 200 && xhr.status < 300 && data.job) {
      if (data.warning) toast(data.warning, "warning", "Heads up");
      state.pendingFile = null;
      state.currentJob = data.job;
      state.transcript = { editing: false, query: "", follow: true, activeIndex: -1 };
      setView("job");
      startJobPolling(data.job.id);
      refreshLibrary();
    } else {
      toast(data.error || "Upload failed.", "error", "Could not start");
      startBtn.disabled = false;
      progressHost.innerHTML = "";
    }
  };
  xhr.onerror = () => {
    toast("The upload could not be completed. Is the app still running?", "error", "Network error");
    startBtn.disabled = false;
  };
  xhr.send(form);
}

/* ------------------------------------------------------------------ *
 * View: Job workspace
 * ------------------------------------------------------------------ */
function renderJob() {
  const job = state.currentJob;
  if (!job) {
    setView("library");
    return;
  }
  const active = isActiveStatus(job.status);
  viewRoot.innerHTML =
    '<div class="row" style="margin-bottom:16px">' +
    '<button class="btn btn-ghost btn-sm" id="backBtn">← Back to library</button>' +
    "</div>" +
    '<div class="card"><div class="card-body">' +
    '<div class="row wrap" style="justify-content:space-between;align-items:flex-start;gap:14px">' +
    "<div style=\"min-width:0\">" +
    '<h1 id="jobTitle" style="font-size:1.5rem">' + escapeHtml(job.title) + "</h1>" +
    '<div class="row wrap" style="gap:10px;margin-top:8px">' +
    '<span id="jobStatus">' + statusBadge(job.status) + "</span>" +
    '<span class="muted" style="font-size:12.5px">' + escapeHtml(modelLabel(job.model)) + " · " +
    escapeHtml(languageLabel(job.language)) + " · " + (job.task === "translate" ? "Translated to English" : "Original language") +
    (job.duration ? " · " + fmtDuration(job.duration) : "") + "</span>" +
    "</div></div>" +
    '<div class="row" style="gap:8px">' +
    '<button class="btn btn-sm" id="renameBtn">' + icon("edit", 15) + "Rename</button>" +
    '<button class="btn btn-danger btn-sm" id="deleteBtn">' + icon("trash", 15) + "Delete</button>" +
    "</div></div>" +
    '<div id="jobProgress"></div>' +
    '<div id="jobError"></div>' +
    "</div></div>" +
    '<div id="jobMedia" class="mt"></div>' +
    '<div id="jobTranscript" class="mt"></div>';

  $("#backBtn").onclick = () => setView("library");
  $("#renameBtn").onclick = renameCurrentJob;
  $("#deleteBtn").onclick = deleteCurrentJob;

  updateJobLive();
  renderJobError();
  renderJobMedia();
  renderJobTranscript();
}

function updateJobLive() {
  const job = state.currentJob;
  if (!job) return;
  const statusHost = $("#jobStatus");
  if (statusHost) statusHost.innerHTML = statusBadge(job.status);
  const live = isActiveStatus(job.status);
  const host = $("#jobProgress");
  if (!host) return;

  if (!live) {
    host.innerHTML = "";
    return;
  }

  const phase = job.phase || job.status;
  const message = job.message || "Working…";
  let determinate = job.progress > 0 && phase === "running";
  if (phase === "loading" && job.downloadProgress != null) determinate = true;

  const pct = phase === "loading" && job.downloadProgress != null
    ? Math.round(job.downloadProgress * 100)
    : Math.round((job.progress || 0) * 100);

  host.innerHTML =
    '<div class="progress-wrap mt">' +
    '<div class="progress' + (determinate ? "" : " indeterminate") + '">' +
    '<div class="bar" style="width:' + Math.max(pct, determinate ? 2 : 38) + '%"></div></div>' +
    '<div class="progress-meta"><span>' + escapeHtml(message) +
    (phase === "loading" && job.downloadProgress != null ? " (downloading " + pct + "%)" : "") +
    "</span><span>" + (determinate ? pct + "%" : "processing") + "</span></div></div>";
}

function renderJobError() {
  const job = state.currentJob;
  const host = $("#jobError");
  if (!host) return;
  if (job.status === "failed" || job.status === "interrupted") {
    host.innerHTML =
      '<div class="alert error mt">' + icon("alert", 18) +
      "<div><strong>Transcription failed</strong><br>" + escapeHtml(job.error || "An unknown error occurred.") +
      '<div class="mt"><button class="btn btn-sm" id="retryBtn">' + icon("refresh", 15) + "Retry</button></div></div></div>";
    const retry = $("#retryBtn");
    if (retry) retry.onclick = retryJob;
  } else if (job.status === "cancelled") {
    host.innerHTML =
      '<div class="alert info mt">' + icon("info", 18) +
      "<div><strong>Cancelled</strong><br>This job was cancelled before it finished.</div></div>";
  } else {
    host.innerHTML = "";
  }
}

function renderJobMedia() {
  const job = state.currentJob;
  const host = $("#jobMedia");
  if (!host) return;
  if (!job.hasMedia || !["completed", "cancelled", "failed"].includes(job.status)) {
    host.innerHTML = "";
    return;
  }
  const src = "/api/jobs/" + job.id + "/media";
  const inner = videoExt(job.sourceName)
    ? '<video id="player" class="media-frame" controls preload="metadata" playsinline src="' + src + '"></video>'
    : '<audio id="player" class="audio-preview" controls preload="metadata" src="' + src + '"></audio>';
  host.innerHTML = '<div class="card card-pad">' + inner + "</div>";
  const player = $("#player");
  if (player && job.segments && job.segments.length) {
    player.ontimeupdate = () => syncActiveSegment(player.currentTime);
  }
}

function renderJobTranscript() {
  const job = state.currentJob;
  const host = $("#jobTranscript");
  if (!host) return;

  if (!["completed", "cancelled", "failed", "interrupted"].includes(job.status)) {
    host.innerHTML = "";
    return;
  }

  const segments = job.segments || [];
  const hasWordTimes = segments.some((seg) => Array.isArray(seg.words) && seg.words.length);
  if (!segments.length && !(job.text || "").trim()) {
    host.innerHTML =
      '<div class="card"><div class="empty-state">' + icon("mic", 24) +
      "<h3>No transcript yet</h3><p>Results will appear here once transcription completes.</p></div></div>";
    return;
  }

  const text = transcriptText(segments) || job.text || "";
  const words = countWords(text);
  const canExport = job.status === "completed" || segments.length > 0;

  host.innerHTML =
    '<div class="card">' +
    '<div class="transcript-toolbar">' +
    '<div class="search-box">' + icon("search", 16) +
    '<input type="search" id="tSearch" placeholder="Search transcript…" value="' + escapeHtml(state.transcript.query) + '" /></div>' +
    '<span class="faint" style="font-size:12px" id="matchCount"></span>' +
    '<div class="spacer"></div>' +
    '<button class="btn btn-sm" id="followBtn" aria-pressed="' + (state.transcript.follow ? 'true' : 'false') + '">' + (state.transcript.follow ? 'Following playback' : 'Resume sync') + '</button>' +
    '<button class="btn btn-sm" id="copyBtn">' + icon("copy", 15) + "Copy</button>" +
    '<button class="btn btn-sm" id="editBtn" data-active="' + (state.transcript.editing ? "true" : "false") + '">' +
    icon("edit", 15) + (state.transcript.editing ? "Editing" : "Edit") + "</button>" +
    (state.transcript.editing
      ? '<button class="btn btn-primary btn-sm" id="saveBtn">' + icon("save", 15) + "Save changes</button>"
      : "") +
    "</div>" +
    '<div id="transcriptBody"></div>' +
    (hasWordTimes ? '<div class="transcript-timing-note">Word timestamps are shown below each segment where Whisper returned them.</div>' : '') +
    '<div class="transcript-toolbar" style="border-top:1px solid var(--border);border-bottom:none">' +
    '<span class="faint" style="font-size:12.5px">' + words + " words · " + text.length + " characters · " + segments.length + " segments</span>" +
    '<div class="spacer"></div>' +
    '<span class="faint" style="font-size:12px;margin-right:6px">Export</span>' +
    '<div class="row wrap" style="gap:6px" id="exportRow"></div>' +
    "</div></div>";

  renderTranscriptBody();
  renderExportRow();

  $("#tSearch").oninput = (e) => {
    state.transcript.query = e.target.value;
    renderTranscriptBody();
  };
  $("#copyBtn").onclick = copyTranscript;
  $("#followBtn").onclick = () => {
    state.transcript.follow = true;
    const player = $("#player");
    if (player) syncActiveSegment(player.currentTime);
    highlightActiveSegment(true);
    const button = $("#followBtn");
    button.textContent = "Following playback";
    button.setAttribute("aria-pressed", "true");
  };
  $("#editBtn").onclick = () => {
    state.transcript.editing = !state.transcript.editing;
    renderJobTranscript();
  };
  const saveBtn = $("#saveBtn");
  if (saveBtn) saveBtn.onclick = saveTranscriptEdits;
  void canExport;
}

function renderExportRow() {
  const row = $("#exportRow");
  if (!row) return;
  row.innerHTML = state.formats
    .map(
      (f) =>
        '<a class="btn btn-sm" href="/api/jobs/' + state.currentJob.id + "/export/" + f.id +
        '" data-export-format="' + escapeHtml(f.id) + '" download>' + icon("download", 14) + escapeHtml(f.id.toUpperCase()) + "</a>"
    )
    .join("");
  $$("[data-export-format]", row).forEach((link) => {
    link.onclick = async (event) => {
      event.preventDefault();
      const format = link.dataset.exportFormat;
      try {
        const response = await fetch(link.href, { cache: "no-store" });
        if (!response.ok) {
          let message = "Export failed (" + response.status + ").";
          try { message = (await response.json()).error || message; } catch (err) { /* keep status */ }
          throw new Error(message);
        }
        const mime = (response.headers.get("content-type") || "").toLowerCase();
        if (mime.startsWith("audio/") || mime.startsWith("video/")) {
          throw new Error("The server returned the media file instead of the " + format.toUpperCase() + " transcript. Restart HawkTranscriber and try again.");
        }
        const blob = await response.blob();
        const disposition = response.headers.get("content-disposition") || "";
        const nameMatch = disposition.match(/filename="?([^";]+)"?/i);
        const filename = nameMatch ? nameMatch[1] : (state.currentJob.title || "transcript") + "." + format;
        const url = URL.createObjectURL(blob);
        const download = document.createElement("a");
        download.href = url;
        download.download = filename;
        document.body.appendChild(download);
        download.click();
        download.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (err) {
        toast(err.message, "error", "Export failed");
      }
    };
  });
}

function renderTranscriptBody() {
  const host = $("#transcriptBody");
  if (!host) return;
  const job = state.currentJob;
  const segments = job.segments || [];
  const query = state.transcript.query.trim().toLowerCase();
  const editing = state.transcript.editing;

  let visible = segments.map((seg, index) => ({ seg, index }));
  if (query) {
    visible = visible.filter((item) => (item.seg.text || "").toLowerCase().includes(query));
  }

  const matches = query ? visible.length : segments.length;
  const matchCount = $("#matchCount");
  if (matchCount) matchCount.textContent = query ? matches + " match" + (matches === 1 ? "" : "es") : "";

  if (!visible.length) {
    host.innerHTML =
      '<div class="empty-state">' + icon("search", 22) +
      "<h3>No matches</h3><p>Try a different search term.</p></div>";
    return;
  }

  if (editing) {
    host.innerHTML =
      '<div class="segments" id="segmentsList">' +
      visible
        .map(
          ({ seg, index }) =>
            '<div class="segment editing" data-index="' + index + '">' +
            '<span class="ts">' + fmtClock(seg.start) + "</span>" +
            '<textarea data-index="' + index + '" rows="2">' + escapeHtml(seg.text || "") + "</textarea>" +
            renderWordTimes(seg.words) +
            "</div>"
        )
        .join("") +
      "</div>";
    return;
  }

  host.innerHTML =
    '<div class="segments" id="segmentsList">' +
    visible
      .map(
        ({ seg, index }) =>
          '<div class="segment" data-index="' + index + '" role="button" tabindex="0">' +
          '<span class="ts">' + fmtClock(seg.start) + "</span>" +
          '<span class="text">' + highlight((seg.text || "").trim(), state.transcript.query) + "</span>" +
          renderWordTimes(seg.words) +
          "</div>"
      )
      .join("") +
    "</div>";

  $$("#segmentsList .segment").forEach((node) => {
    const seek = () => seekToSegment(Number(node.dataset.index));
    node.onclick = seek;
    node.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        seek();
      }
    };
  });
  const list = $("#segmentsList");
  if (list) {
    const pauseFollow = () => {
      if (!state.transcript.follow) return;
      state.transcript.follow = false;
      const button = $("#followBtn");
      if (button) {
        button.textContent = "Resume sync";
        button.setAttribute("aria-pressed", "false");
      }
    };
    list.addEventListener("wheel", pauseFollow, { passive: true });
    list.addEventListener("touchstart", pauseFollow, { passive: true });
  }
}

function renderWordTimes(words) {
  if (!Array.isArray(words) || !words.length) return "";
  return '<div class="word-times" aria-label="Word timestamps">' + words.map((word) => {
    const token = typeof word.word === "string" ? word.word : "";
    return '<span class="word-time"><time>' + fmtClock(word.start) + '</time> ' + escapeHtml(token.trim()) + '</span>';
  }).join("") + '</div>';
}

function seekToSegment(index) {
  const job = state.currentJob;
  const segment = (job.segments || [])[index];
  if (!segment) return;
  const player = $("#player");
  state.transcript.follow = true;
  state.transcript.activeIndex = index;
  highlightActiveSegment();
  if (player) {
    player.currentTime = segment.start || 0;
    player.play().catch(() => {});
    player.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  const followButton = $("#followBtn");
  if (followButton) {
    followButton.textContent = "Following playback";
    followButton.setAttribute("aria-pressed", "true");
  }
}

function syncActiveSegment(time) {
  const segments = state.currentJob.segments || [];
  let index = -1;
  for (let i = 0; i < segments.length; i += 1) {
    const s = segments[i];
    if (time >= (s.start || 0) && time < (s.end || s.start || 0)) {
      index = i;
      break;
    }
  }
  if (index === state.transcript.activeIndex) return;
  state.transcript.activeIndex = index;
  highlightActiveSegment(true);
}

function highlightActiveSegment(scroll) {
  $$("#segmentsList .segment").forEach((node) => {
    const isActive = Number(node.dataset.index) === state.transcript.activeIndex;
    node.classList.toggle("active", isActive);
    if (isActive && scroll && state.transcript.follow) {
      node.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
}

async function copyTranscript() {
  const text = transcriptText(state.currentJob.segments) || state.currentJob.text || "";
  try {
    await navigator.clipboard.writeText(text);
    toast("The full transcript was copied to your clipboard.", "success", "Copied");
  } catch (err) {
    toast("Copy failed. Select the text manually instead.", "error");
  }
}

async function saveTranscriptEdits() {
  const job = state.currentJob;
  const segments = (job.segments || []).map((s) => Object.assign({}, s));
  $$("#segmentsList textarea").forEach((area) => {
    const index = Number(area.dataset.index);
    if (segments[index]) segments[index].text = area.value.trim();
  });
  const text = transcriptText(segments);
  busy(true);
  try {
    const { job: updated } = await api("/api/jobs/" + job.id, {
      method: "PATCH",
      body: { segments, text, title: job.title },
    });
    state.currentJob = updated;
    state.transcript.editing = false;
    toast("Your changes were saved.", "success", "Saved");
    renderJobTranscript();
  } catch (err) {
    toast(err.message, "error", "Could not save");
  } finally {
    busy(false);
  }
}

async function renameCurrentJob() {
  const job = state.currentJob;
  const value = await promptModal({
    title: "Rename transcript",
    label: "Title",
    value: job.title,
    confirmLabel: "Rename",
  });
  if (value == null || !value) return;
  try {
    const { job: updated } = await api("/api/jobs/" + job.id, {
      method: "PATCH",
      body: { title: value },
    });
    state.currentJob = updated;
    $("#jobTitle").textContent = updated.title;
    refreshLibrary();
    toast("Transcript renamed.", "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function deleteCurrentJob() {
  const job = state.currentJob;
  const ok = await confirmModal({
    title: "Delete transcript?",
    message: "This permanently removes the transcript" + (job.hasMedia ? " and its stored media file" : "") + ". This cannot be undone.",
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    await api("/api/jobs/" + job.id, { method: "DELETE" });
    toast("Transcript deleted.", "success");
    state.currentJob = null;
    await refreshLibrary();
    setView("library");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function retryJob() {
  const job = state.currentJob;
  if (!job.hasMedia) {
    toast("The original media file is no longer available.", "error");
    return;
  }
  busy(true);
  try {
    const response = await fetch("/api/jobs/" + job.id + "/media");
    const blob = await response.blob();
    const file = new File([blob], job.sourceName, { type: blob.type || "application/octet-stream" });
    const form = new FormData();
    form.append("file", file);
    form.append("model", job.model);
    form.append("language", job.language || "auto");
    form.append("task", job.task || "transcribe");
    form.append("word_timestamps", job.wordTimestamps ? "1" : "0");
    const data = await api("/api/jobs", { method: "POST", body: form });
    state.currentJob = data.job;
    state.transcript = { editing: false, query: "", follow: true, activeIndex: -1 };
    renderJob();
    startJobPolling(data.job.id);
    refreshLibrary();
  } catch (err) {
    toast(err.message, "error", "Retry failed");
  } finally {
    busy(false);
  }
}

/* ------------------------------------------------------------------ *
 * View: Library
 * ------------------------------------------------------------------ */
function renderLibrary() {
  const filters = [
    { id: "all", label: "All" },
    { id: "completed", label: "Completed" },
    { id: "active", label: "In progress" },
    { id: "failed", label: "Failed" },
  ];
  const jobs = filteredJobs();

  viewRoot.innerHTML =
    '<header class="page-head"><h1>Library</h1>' +
    '<p class="lede">Your transcripts are stored locally and stay available between sessions.</p></header>' +
    '<div class="row wrap" style="margin-bottom:16px;gap:12px">' +
    '<div class="search-box" style="max-width:340px;flex:1">' + icon("search", 16) +
    '<input type="search" id="libSearch" placeholder="Search transcripts…" value="' + escapeHtml(state.libraryQuery) + '" /></div>' +
    '<div class="chips" id="libChips">' +
    filters
      .map(
        (f) => '<button class="chip ' + (state.libraryFilter === f.id ? "active" : "") + '" data-filter="' + f.id + '">' + f.label + "</button>"
      )
      .join("") +
    "</div>" +
    '<div class="spacer"></div>' +
    '<button class="btn btn-primary btn-sm" id="libNew">' + icon("plus", 15) + "New</button>" +
    "</div>" +
    '<div id="libBody"></div>';

  $("#libNew").onclick = () => {
    state.pendingFile = null;
    setView("new");
  };
  $("#libSearch").oninput = (e) => {
    state.libraryQuery = e.target.value;
    renderLibrary();
    const el = $("#libSearch");
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  };
  $$("#libChips .chip").forEach((chip) => {
    chip.onclick = () => {
      state.libraryFilter = chip.dataset.filter;
      renderLibrary();
    };
  });
  void jobs;
  renderLibraryBody();
}

function filteredJobs() {
  let jobs = state.jobs.slice();
  if (state.libraryFilter === "active") jobs = jobs.filter((j) => isActiveStatus(j.status));
  else if (state.libraryFilter !== "all") jobs = jobs.filter((j) => j.status === state.libraryFilter);
  const query = state.libraryQuery.trim().toLowerCase();
  if (query) {
    jobs = jobs.filter(
      (j) =>
        (j.title || "").toLowerCase().includes(query) ||
        (j.sourceName || "").toLowerCase().includes(query)
    );
  }
  return jobs;
}

function renderLibraryBody() {
  const host = $("#libBody");
  if (!host) return;
  const jobs = filteredJobs();
  if (!jobs.length) {
    host.innerHTML =
      '<div class="card"><div class="empty-state">' + icon("layers", 24) +
      "<h3>" + (state.jobs.length ? "No matching transcripts" : "Your library is empty") + "</h3>" +
      "<p>" + (state.jobs.length
        ? "Try a different search or filter."
        : "Transcribe your first file to see it here.") + "</p>" +
      '<button class="btn btn-primary btn-sm" id="emptyNew">' + icon("plus", 15) + "New transcription</button>" +
      "</div></div>";
    const btn = $("#emptyNew");
    if (btn) btn.onclick = () => { state.pendingFile = null; setView("new"); };
    return;
  }
  host.innerHTML = '<div class="list" id="libList">' + jobs.map((j) => libraryFullRow(j)).join("") + "</div>";
  bindLibraryRows(host);
}

function libraryRow(job) {
  const meta = statusMeta(job.status);
  return (
    '<div class="list-row" data-id="' + job.id + '">' +
    '<span class="thumb">' + icon(videoExt(job.sourceName) ? "file" : "mic", 18) + "</span>" +
    '<div class="info"><div class="name">' + escapeHtml(job.title) + "</div>" +
    '<div class="sub"><span>' + fmtDate(job.createdAt) + "</span>" +
    (job.duration ? "<span>" + fmtDuration(job.duration) + "</span>" : "") +
    "<span>" + escapeHtml(modelLabel(job.model)) + "</span></div></div>" +
    '<span class="badge ' + meta.cls + '"><i class="dot"></i>' + meta.label + "</span>" +
    "</div>"
  );
}

function libraryFullRow(job) {
  const meta = statusMeta(job.status);
  return (
    '<div class="list-row" data-id="' + job.id + '">' +
    '<span class="thumb">' + icon(videoExt(job.sourceName) ? "file" : "mic", 18) + "</span>" +
    '<div class="info"><div class="name">' + escapeHtml(job.title) + "</div>" +
    '<div class="sub"><span>' + fmtDate(job.createdAt) + "</span>" +
    (job.duration ? "<span>" + fmtDuration(job.duration) + "</span>" : "") +
    "<span>" + escapeHtml(modelLabel(job.model)) + "</span>" +
    "<span>" + escapeHtml(languageLabel(job.language)) + "</span></div></div>" +
    '<span class="badge ' + meta.cls + '"><i class="dot"></i>' + meta.label + "</span>" +
    '<div class="actions">' +
    (job.status === "completed"
      ? '<a class="btn btn-sm" href="/api/jobs/' + job.id + '/export/txt" download title="Download TXT">' + icon("download", 15) + "</a>"
      : "") +
    '<button class="btn btn-sm" data-rename="' + job.id + '" title="Rename">' + icon("edit", 15) + "</button>" +
    '<button class="btn btn-sm btn-danger" data-delete="' + job.id + '" title="Delete">' + icon("trash", 15) + "</button>" +
    "</div></div>"
  );
}

function bindLibraryRows(root) {
  if (!root) return;
  $$(".list-row", root).forEach((row) => {
    row.onclick = (e) => {
      if (e.target.closest("button") || e.target.closest("a")) return;
      openJob(row.dataset.id);
    };
  });
  $$("[data-rename]", root).forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const job = state.jobs.find((j) => j.id === btn.dataset.rename);
      if (!job) return;
      const value = await promptModal({ title: "Rename transcript", label: "Title", value: job.title, confirmLabel: "Rename" });
      if (value == null || !value) return;
      try {
        await api("/api/jobs/" + job.id, { method: "PATCH", body: { title: value } });
        await refreshLibrary();
        toast("Transcript renamed.", "success");
      } catch (err) {
        toast(err.message, "error");
      }
    };
  });
  $$("[data-delete]", root).forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const job = state.jobs.find((j) => j.id === btn.dataset.delete);
      if (!job) return;
      const ok = await confirmModal({
        title: "Delete transcript?",
        message: "This permanently removes \"" + job.title + "\" and any stored media.",
        confirmLabel: "Delete",
        danger: true,
      });
      if (!ok) return;
      try {
        await api("/api/jobs/" + job.id, { method: "DELETE" });
        await refreshLibrary();
        toast("Transcript deleted.", "success");
      } catch (err) {
        toast(err.message, "error");
      }
    };
  });
}

async function openJob(id) {
  try {
    busy(true);
    const { job } = await api("/api/jobs/" + id);
    state.currentJob = job;
    state.transcript = { editing: false, query: "", follow: true, activeIndex: -1 };
    setView("job");
    if (isActiveStatus(job.status)) startJobPolling(job.id);
  } catch (err) {
    toast(err.message, "error");
  } finally {
    busy(false);
  }
}

/* ------------------------------------------------------------------ *
 * View: Settings
 * ------------------------------------------------------------------ */
function renderSettings() {
  const s = state.settings;
  const sys = state.system;
  const warnings = sys.warnings || [];
  viewRoot.innerHTML =
    '<header class="page-head"><h1>Settings</h1>' +
    '<p class="lede">Preferences are remembered between sessions and stored locally.</p></header>' +
    '<div class="stack">' +

    '<div class="card"><div class="card-head"><span class="section-title">Appearance</span></div>' +
    '<div class="card-body"><div class="row wrap" style="gap:20px">' +
    '<div class="field"><label>Theme</label><div class="segmented" id="themeSeg">' +
    ["system", "light", "dark"].map((t) => '<button data-theme="' + t + '" class="' + (s.theme === t ? "active" : "") + '">' + t.charAt(0).toUpperCase() + t.slice(1) + "</button>").join("") +
    "</div></div></div></div></div>" +

    '<div class="card"><div class="card-head"><span class="section-title">Transcription defaults</span></div>' +
    '<div class="card-body"><div class="grid grid-3">' +
    '<div class="field"><label for="setModel">Default model</label><select id="setModel">' +
    state.models.map((m) => '<option value="' + m.name + '"' + (m.name === s.default_model ? " selected" : "") + ">" + escapeHtml(m.label) + "</option>").join("") +
    "</select></div>" +
    '<div class="field"><label for="setLang">Default language</label><select id="setLang">' +
    state.languages.map((l) => '<option value="' + l.code + '"' + (l.code === s.default_language ? " selected" : "") + ">" + escapeHtml(l.label) + "</option>").join("") +
    "</select></div>" +
    '<div class="field"><label for="setTask">Default task</label><select id="setTask">' +
    '<option value="transcribe"' + (s.default_task === "transcribe" ? " selected" : "") + ">Transcribe</option>" +
    '<option value="translate"' + (s.default_task === "translate" ? " selected" : "") + ">Translate to English</option>" +
    "</select></div>" +
    "</div>" +
    '<div class="divider mt"></div>' +
    '<div class="row wrap mt" style="gap:26px">' +
    '<label class="switch"><input type="checkbox" id="setWordTs" ' + (s.word_timestamps ? "checked" : "") + ' /><span class="track"></span><span class="switch-label">Word timestamps by default<small>Slower but more precise</small></span></label>' +
    '<label class="switch"><input type="checkbox" id="setCondition" ' + (s.condition_on_previous_text ? "checked" : "") + ' /><span class="track"></span><span class="switch-label">Use previous text as context<small>Improves continuity on long audio</small></span></label>' +
    "</div></div></div>" +

    '<div class="card"><div class="card-head"><span class="section-title">Storage &amp; history</span></div>' +
    '<div class="card-body">' +
    '<div class="grid grid-3" style="margin-bottom:18px">' +
    statCard(sys.stats.total, "Total jobs") +
    statCard(sys.stats.completed, "Completed") +
    statCard(fmtDuration(sys.stats.totalMediaSeconds), "Media transcribed") +
    "</div>" +
    '<dl class="kv">' +
    kv("Data folder", sys.paths.data) +
    kv("Transcripts &amp; media", sys.paths.media) +
    kv("Model cache", sys.paths.models) +
    kv("History database", sys.paths.database) +
    "</dl>" +
    '<div class="row wrap mt" style="gap:10px">' +
    '<button class="btn btn-sm" id="copyPaths">' + icon("copy", 15) + "Copy data folder path</button>" +
    '<button class="btn btn-danger btn-sm" id="clearHistory">' + icon("trash", 15) + "Clear history</button>" +
    "</div></div></div>" +

    '<div class="card"><div class="card-head"><span class="section-title">Diagnostics</span></div>' +
    '<div class="card-body">' +
    (warnings.length
      ? warnings.map((w) => '<div class="alert warning" style="margin-bottom:10px">' + icon("alert", 17) + '<div class="alert-body">' + escapeHtml(w) + "</div></div>").join("")
      : '<div class="alert success" style="margin-bottom:16px">' + icon("check", 17) + '<div class="alert-body">All required dependencies were detected.</div></div>') +
    '<dl class="kv">' +
    kv("Compute device", sys.deviceLabel) +
    kv("FFmpeg", sys.ffmpegAvailable ? (sys.ffmpegVersion || "Available") : "Not found") +
    kv("PyTorch", sys.torchVersion + (sys.cudaAvailable ? " (CUDA available)" : " (CPU only)")) +
    kv("Whisper", sys.whisperVersion) +
    kv("Python", sys.pythonVersion) +
    kv("Platform", sys.platform) +
    kv("Memory", sys.totalRamGb + " GB total · " + sys.availableRamGb + " GB free") +
    "</dl>" +
    '<div class="mt"><button class="btn btn-sm" id="refreshDiag">' + icon("refresh", 15) + "Refresh diagnostics</button></div>" +
    "</div></div>" +

    "</div>";

  $$("#themeSeg button").forEach((btn) => {
    btn.onclick = async () => {
      state.settings.theme = btn.dataset.theme;
      applyTheme(btn.dataset.theme);
      $$("#themeSeg button").forEach((b) => b.classList.toggle("active", b === btn));
      await saveSettings({ theme: btn.dataset.theme });
    };
  });
  $("#setModel").onchange = (e) => saveSettings({ default_model: e.target.value });
  $("#setLang").onchange = (e) => saveSettings({ default_language: e.target.value });
  $("#setTask").onchange = (e) => saveSettings({ default_task: e.target.value });
  $("#setWordTs").onchange = (e) => saveSettings({ word_timestamps: e.target.checked });
  $("#setCondition").onchange = (e) => saveSettings({ condition_on_previous_text: e.target.checked });
  $("#copyPaths").onclick = async () => {
    try {
      await navigator.clipboard.writeText(sys.paths.data);
      toast("Data folder path copied.", "success");
    } catch (err) {
      toast(sys.paths.data, "info", "Data folder");
    }
  };
  $("#clearHistory").onclick = clearHistoryFlow;
  $("#refreshDiag").onclick = async () => {
    state.system = await api("/api/system");
    toast("Diagnostics refreshed.", "success");
    renderSettings();
  };
}

function statCard(value, label) {
  return (
    '<div class="stat-card"><div class="stat-value">' + escapeHtml(String(value)) + "</div>" +
    '<div class="stat-label">' + escapeHtml(label) + "</div></div>"
  );
}

function kv(term, value) {
  return "<dt>" + term + "</dt><dd>" + escapeHtml(value) + "</dd>";
}

async function saveSettings(patch) {
  try {
    const { settings } = await api("/api/settings", { method: "PUT", body: patch });
    state.settings = settings;
    if ("default_model" in patch) state.options.model = settings.default_model;
    if ("default_language" in patch) state.options.language = settings.default_language;
    if ("default_task" in patch) state.options.task = settings.default_task;
    if ("word_timestamps" in patch) state.options.wordTimestamps = settings.word_timestamps;
    toast("Setting saved.", "success");
  } catch (err) {
    toast(err.message, "error", "Could not save setting");
  }
}

async function clearHistoryFlow() {
  const ok = await confirmModal({
    title: "Clear all history?",
    message: "This removes every transcript record and its stored media copy. Download anything you want to keep first.",
    confirmLabel: "Clear everything",
    danger: true,
  });
  if (!ok) return;
  try {
    const result = await api("/api/history/clear", { method: "POST", body: { deleteMedia: true } });
    toast(result.removed + " record(s) removed.", "success", "History cleared");
    await refreshLibrary();
    state.system = await api("/api/system");
    renderSettings();
  } catch (err) {
    toast(err.message, "error");
  }
}

/* ------------------------------------------------------------------ *
 * Keyboard shortcuts
 * ------------------------------------------------------------------ */
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !modalRoot.hidden) closeModal();
  if (e.target.matches("input, textarea, select")) return;
  if (e.key === "/" && state.view === "job") {
    const search = $("#tSearch");
    if (search) {
      e.preventDefault();
      search.focus();
    }
  }
});

init();
