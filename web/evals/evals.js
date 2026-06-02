// EasyAgent eval dashboard — read-only RAG eval runs via gated /api/evals/* endpoints.

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);
const API_BASE_KEY = "easyagent-dashboard-api-base";
const METRICS = ["recall_at_5", "context_precision", "faithfulness", "answer_relevance"];
const VARIANTS = ["keyword", "hybrid", "hybrid_rerank"];
const SERIES_COLORS = ["#6bc97a", "#5b9fd4", "#c97ad4", "#d4a24a", "#e07070", "#9a9890", "#8fd4c4", "#d48f5b"];

const els = {
  apiBase: document.getElementById("api-base"),
  refreshBtn: document.getElementById("refresh-btn"),
  loadError: document.getElementById("load-error"),
  loadMeta: document.getElementById("load-meta"),
  profileSelect: document.getElementById("profile-select"),
  indexBadge: document.getElementById("index-badge"),
  trend: document.getElementById("trend"),
  variantToggles: document.getElementById("variant-toggles"),
  casesTable: document.querySelector("#cases-table tbody"),
  runLabel: document.getElementById("run-label"),
  caseDetail: document.getElementById("case-detail"),
  brandMark: document.getElementById("brand-mark"),
};

let state = {
  defaultProfile: "personal-agent",
  profiles: [],
  runs: [],
  indexStatus: null,
  latestRun: null,
  selectedCaseId: null,
};

function defaultApiBase() {
  return LOCAL_HOSTS.has(window.location.hostname) ? "http://127.0.0.1:8001" : "";
}

function apiBase() {
  return (els.apiBase.value || "").trim().replace(/\/$/, "");
}

function saveApiBase() {
  localStorage.setItem(API_BASE_KEY, apiBase());
}

function loadApiBase() {
  els.apiBase.value = localStorage.getItem(API_BASE_KEY) || defaultApiBase();
}

async function fetchJson(path) {
  const base = apiBase();
  if (!base) {
    throw new Error("Set an API base URL (e.g. http://127.0.0.1:8001)");
  }
  const res = await fetch(`${base}${path}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${path} → ${res.status} ${detail.slice(0, 180)}`);
  }
  return res.json();
}

function showError(message) {
  els.loadError.textContent = message;
  els.loadError.classList.remove("hidden");
}

function clearError() {
  els.loadError.textContent = "";
  els.loadError.classList.add("hidden");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function metricClass(value) {
  if (value == null || Number.isNaN(value)) return "";
  if (value < 0.5) return "metric-low";
  if (value < 0.75) return "metric-mid";
  return "metric-high";
}

function fmtMetric(value) {
  if (value == null || Number.isNaN(value)) return "—";
  return Number(value).toFixed(2);
}

function applyBrandAccent(profileId) {
  const profile = state.profiles.find((p) => p.id === profileId);
  const accent = profile?.brand?.accent;
  if (accent) {
    document.documentElement.style.setProperty("--accent", accent);
    els.brandMark.style.background = accent;
  }
}

function renderIndexBadge(payload) {
  const status = payload?.status || "unknown";
  els.indexBadge.textContent = `index: ${status}`;
  els.indexBadge.className = "index-badge";
  if (status === "current") els.indexBadge.classList.add("is-ok");
  else if (status === "stale" || status === "missing") els.indexBadge.classList.add("is-warn");
  else if (status === "error") els.indexBadge.classList.add("is-error");
}

function checkedVariants() {
  return VARIANTS.filter((v) => {
    const input = els.variantToggles.querySelector(`input[value="${v}"]`);
    return input?.checked;
  });
}

function mapX(i, n, pad, w) {
  if (n <= 1) return pad + w / 2;
  return pad + (i / (n - 1)) * w;
}

function mapY(value, pad, h) {
  const clamped = Math.max(0, Math.min(1, value));
  return pad + h - clamped * h;
}

function drawTrend() {
  const canvas = els.trend;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 960;
  const cssH = 280;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const padL = 44;
  const padR = 140;
  const padT = 16;
  const padB = 28;
  const plotW = cssW - padL - padR;
  const plotH = cssH - padT - padB;

  ctx.fillStyle = "#18191c";
  ctx.fillRect(0, 0, cssW, cssH);

  ctx.strokeStyle = "#3a3d45";
  ctx.lineWidth = 1;
  ctx.font = "10px IBM Plex Mono, monospace";
  ctx.fillStyle = "#9a9890";
  for (const tick of [0, 0.25, 0.5, 0.75, 1]) {
    const y = mapY(tick, padT, plotH);
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(padL + plotW, y);
    ctx.stroke();
    ctx.fillText(tick.toFixed(2), 6, y + 3);
  }

  const runs = [...state.runs].reverse();
  const variants = checkedVariants();
  let colorIdx = 0;
  const legend = [];

  for (const metric of METRICS) {
    for (const variant of variants) {
      const color = SERIES_COLORS[colorIdx % SERIES_COLORS.length];
      colorIdx += 1;
      const label = `${variant} · ${metric}`;
      legend.push({ label, color });

      const points = [];
      runs.forEach((run, i) => {
        const val = run.per_variant?.[variant]?.[metric];
        if (val != null && !Number.isNaN(val)) {
          points.push({ x: mapX(i, runs.length, padL, plotW), y: mapY(val, padT, plotH), val });
        }
      });
      if (points.length < 2) {
        if (points.length === 1) {
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(points[0].x, points[0].y, 3, 0, Math.PI * 2);
          ctx.fill();
        }
        continue;
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let j = 1; j < points.length; j += 1) {
        ctx.lineTo(points[j].x, points[j].y);
      }
      ctx.stroke();
      ctx.fillStyle = color;
      for (const p of points) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  let ly = padT;
  ctx.font = "10px IBM Plex Mono, monospace";
  for (const item of legend) {
    ctx.fillStyle = item.color;
    ctx.fillRect(cssW - padR + 8, ly, 10, 10);
    ctx.fillStyle = "#e8e6e1";
    ctx.fillText(item.label, cssW - padR + 22, ly + 9);
    ly += 14;
  }
}

function renderCasesTable() {
  const run = state.latestRun;
  if (!run?.records?.length) {
    els.casesTable.innerHTML = `<tr><td colspan="6" class="muted">No eval records for the latest run.</td></tr>`;
    els.runLabel.textContent = "";
    els.caseDetail.classList.add("hidden");
    return;
  }
  els.runLabel.textContent = run.summary?.run_id ? `run ${run.summary.run_id}` : "";
  els.casesTable.innerHTML = run.records
    .map((rec) => {
      const m = rec.metrics || {};
      const selected = rec.case_id === state.selectedCaseId ? " is-selected" : "";
      return `<tr class="case-row${selected}" data-case-id="${escapeHtml(rec.case_id)}">
        <td><code>${escapeHtml(rec.case_id)}</code></td>
        <td class="${metricClass(m.recall_at_5)}">${fmtMetric(m.recall_at_5)}</td>
        <td class="${metricClass(m.context_precision)}">${fmtMetric(m.context_precision)}</td>
        <td class="${metricClass(m.faithfulness)}">${fmtMetric(m.faithfulness)}</td>
        <td class="${metricClass(m.answer_relevance)}">${fmtMetric(m.answer_relevance)}</td>
        <td>${escapeHtml(rec.status || "—")}</td>
      </tr>`;
    })
    .join("");
}

function renderCaseDetail(rec) {
  if (!rec) {
    els.caseDetail.classList.add("hidden");
    return;
  }
  const chunks = (rec.retrieved || [])
    .map(
      (ch) => `<article class="chunk-card">
        <div>${escapeHtml(ch.path)}:${ch.start_line ?? "?"}-${ch.end_line ?? "?"} · score ${fmtMetric(ch.score)}</div>
        <pre>${escapeHtml(ch.snippet || "")}</pre>
      </article>`
    )
    .join("");
  els.caseDetail.innerHTML = `
    <h3>${escapeHtml(rec.case_id)}</h3>
    <p class="muted">${escapeHtml(rec.query || "")}</p>
    ${chunks || "<p class=\"muted\">No retrieved chunks.</p>"}
    <p class="grader-reason"><strong>Grader:</strong> ${escapeHtml(rec.grader_reasoning || "—")}</p>`;
  els.caseDetail.classList.remove("hidden");
}

async function loadLatestRunRecords(profileId) {
  const latest = state.runs[0];
  if (!latest?.run_id) {
    state.latestRun = null;
    renderCasesTable();
    return;
  }
  state.latestRun = await fetchJson(
    `/api/evals/run/${encodeURIComponent(profileId)}/${encodeURIComponent(latest.run_id)}`
  );
  renderCasesTable();
  if (state.selectedCaseId) {
    const rec = state.latestRun.records.find((r) => r.case_id === state.selectedCaseId);
    renderCaseDetail(rec);
  }
}

async function loadProfileData(profileId) {
  const [runsPayload, indexPayload] = await Promise.all([
    fetchJson(`/api/evals/runs/${encodeURIComponent(profileId)}`),
    fetchJson(`/api/evals/index-status/${encodeURIComponent(profileId)}`),
  ]);
  state.runs = runsPayload.runs || [];
  state.indexStatus = indexPayload;
  renderIndexBadge(indexPayload);
  drawTrend();
  await loadLatestRunRecords(profileId);
}

async function refreshEvals() {
  clearError();
  saveApiBase();
  const started = performance.now();
  try {
    const profilesPayload = await fetchJson("/api/profiles");
    state.defaultProfile = profilesPayload.default || "personal-agent";
    state.profiles = profilesPayload.profiles || [];
    const current = els.profileSelect.value;
    els.profileSelect.innerHTML = state.profiles
      .map(
        (p) =>
          `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)} (${escapeHtml(p.id)})</option>`
      )
      .join("");
    const profileId =
      current && state.profiles.some((p) => p.id === current)
        ? current
        : state.defaultProfile;
    els.profileSelect.value = profileId;
    applyBrandAccent(profileId);
    await loadProfileData(profileId);
    const ms = Math.round(performance.now() - started);
    els.loadMeta.textContent = `Updated ${new Date().toLocaleTimeString()} · ${apiBase()} · ${ms}ms`;
  } catch (err) {
    showError(err instanceof Error ? err.message : String(err));
    els.loadMeta.textContent = "";
  }
}

els.refreshBtn.addEventListener("click", () => refreshEvals());
els.apiBase.addEventListener("change", () => refreshEvals());
els.profileSelect.addEventListener("change", async () => {
  clearError();
  try {
    applyBrandAccent(els.profileSelect.value);
    await loadProfileData(els.profileSelect.value);
  } catch (err) {
    showError(err instanceof Error ? err.message : String(err));
  }
});
els.variantToggles.addEventListener("change", () => drawTrend());
els.casesTable.addEventListener("click", (ev) => {
  const row = ev.target.closest("tr.case-row");
  if (!row) return;
  state.selectedCaseId = row.dataset.caseId;
  renderCasesTable();
  const rec = state.latestRun?.records?.find((r) => r.case_id === state.selectedCaseId);
  renderCaseDetail(rec);
});
window.addEventListener("resize", () => drawTrend());

loadApiBase();
refreshEvals();
