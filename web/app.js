// EasyAgent technical dashboard — read-only view of runtime state via REST APIs.

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);
const API_BASE_KEY = "easyagent-dashboard-api-base";

const ENDPOINTS = [
  { method: "GET", path: "/api/status", note: "Aggregated runtime, budget, limits, registry" },
  { method: "GET", path: "/api/health", note: "Liveness and active session count" },
  { method: "GET", path: "/api/budget", note: "Daily token budget usage" },
  { method: "GET", path: "/api/models", note: "Models available for the configured API keys" },
  { method: "GET", path: "/api/profiles", note: "Bundled agent profiles" },
  { method: "GET", path: "/api/profile?profile_id=", note: "One profile with tool schemas" },
  { method: "GET", path: "/api/rag/index?profile_id=", note: "RAG index health for a profile" },
  { method: "POST", path: "/api/chat", note: "SSE chat stream (not used by this dashboard)" },
];

const els = {
  apiBase: document.getElementById("api-base"),
  refreshBtn: document.getElementById("refresh-btn"),
  loadError: document.getElementById("load-error"),
  loadMeta: document.getElementById("load-meta"),
  runtimeGrid: document.getElementById("runtime-grid"),
  limitsList: document.getElementById("limits-list"),
  budgetPanel: document.getElementById("budget-panel"),
  modelsTable: document.querySelector("#models-table tbody"),
  profilesTable: document.querySelector("#profiles-table tbody"),
  profileSelect: document.getElementById("profile-select"),
  profileDetail: document.getElementById("profile-detail"),
  profileDetailTitle: document.getElementById("profile-detail-title"),
  profileDescription: document.getElementById("profile-description"),
  profileTools: document.getElementById("profile-tools"),
  profileMcp: document.getElementById("profile-mcp"),
  profileSchemas: document.getElementById("profile-schemas"),
  ragPanel: document.getElementById("rag-panel"),
  ragProfileLabel: document.getElementById("rag-profile-label"),
  endpointList: document.getElementById("endpoint-list"),
};

let state = {
  defaultProfile: "",
  profiles: [],
};

function defaultApiBase() {
  return LOCAL_HOSTS.has(window.location.hostname) ? "http://127.0.0.1:8001" : "";
}

function apiBase() {
  const value = (els.apiBase.value || "").trim().replace(/\/$/, "");
  return value;
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

function fmtNumber(value) {
  return new Intl.NumberFormat().format(Number(value) || 0);
}

function pct(used, limit) {
  if (!limit) return 0;
  return Math.min(100, Math.round((used / limit) * 100));
}

function renderStatCards(status) {
  const { health, budget, registry, defaults } = status;
  const cards = [
    ["Status", health.status],
    ["Sessions", fmtNumber(health.sessions)],
    ["Native tools", fmtNumber(registry.native_tools)],
    ["Models live", `${registry.models_available}/${registry.models_configured}`],
    ["Default profile", defaults.profile],
    ["Default model", defaults.model],
    ["Budget left", fmtNumber(budget.remaining)],
  ];
  els.runtimeGrid.innerHTML = cards
    .map(
      ([label, value]) => `
        <article class="stat-card">
          <span class="stat-label">${label}</span>
          <span class="stat-value">${escapeHtml(String(value))}</span>
        </article>`
    )
    .join("");
}

function renderLimits(status) {
  const rows = Object.entries(status.limits).map(([key, value]) => {
    const label = key.replaceAll("_", " ");
    return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd></div>`;
  });
  const ragRows = [
    ["embedding backend", status.rag.embedding_backend],
    ["embedding model", status.rag.embedding_model || "—"],
    ["providers wired", status.registry.providers.join(", ")],
  ].map(
    ([label, value]) =>
      `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd></div>`
  );
  els.limitsList.innerHTML = rows.join("") + ragRows.join("");
}

function renderBudget(budget) {
  const usedPct = pct(budget.used, budget.limit);
  els.budgetPanel.innerHTML = `
    <div class="budget-bar" aria-hidden="true"><span style="width:${usedPct}%"></span></div>
    <div class="budget-meta">
      <span>${fmtNumber(budget.used)} / ${fmtNumber(budget.limit)} tokens (${usedPct}%)</span>
      <span>date ${escapeHtml(budget.date)} · ${fmtNumber(budget.remaining)} remaining</span>
    </div>`;
}

function renderModels(modelsPayload) {
  const defaultId = modelsPayload.default;
  els.modelsTable.innerHTML = (modelsPayload.models || [])
    .map((model) => {
      const isDefault = model.id === defaultId;
      return `<tr>
        <td><code>${escapeHtml(model.id)}</code></td>
        <td>${escapeHtml(model.label)}</td>
        <td>${escapeHtml(model.vendor)}</td>
        <td><code>${escapeHtml(model.provider)}</code></td>
        <td>${isDefault ? '<span class="badge badge-default">default</span>' : ""}</td>
      </tr>`;
    })
    .join("");
}

function renderProfiles(profilesPayload) {
  state.defaultProfile = profilesPayload.default || "";
  state.profiles = profilesPayload.profiles || [];
  els.profilesTable.innerHTML = state.profiles
    .map((profile) => {
      const isDefault = profile.id === state.defaultProfile;
      const mcp = (profile.mcp_servers || []).length;
      return `<tr>
        <td><code>${escapeHtml(profile.id)}</code></td>
        <td>${escapeHtml(profile.label)}</td>
        <td>${profile.tools.length}</td>
        <td>${mcp ? mcp : "—"}</td>
        <td>${isDefault ? '<span class="badge badge-default">default</span>' : ""}</td>
      </tr>`;
    })
    .join("");

  const current = els.profileSelect.value;
  els.profileSelect.innerHTML = state.profiles
    .map(
      (profile) =>
        `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.label)} (${escapeHtml(profile.id)})</option>`
    )
    .join("");
  const next = state.profiles.some((p) => p.id === current)
    ? current
    : state.defaultProfile || state.profiles[0]?.id || "";
  if (next) {
    els.profileSelect.value = next;
  }
}

function renderProfileDetail(profile) {
  els.profileDetail.classList.remove("hidden");
  els.profileDetailTitle.textContent = `${profile.label} (${profile.id})`;
  els.profileDescription.textContent = profile.description || "No description.";
  els.profileTools.innerHTML = (profile.tools || [])
    .map((tool) => `<li><code>${escapeHtml(tool)}</code></li>`)
    .join("");
  const mcp = profile.mcp_servers || [];
  els.profileMcp.innerHTML = mcp.length
    ? mcp.map((name) => `<li><code>${escapeHtml(name)}</code></li>`).join("")
    : '<li class="muted">none configured</li>';
  els.profileSchemas.textContent = JSON.stringify(profile.tool_schemas || [], null, 2);
}

function renderRag(ragPayload, profileId) {
  els.ragProfileLabel.textContent = profileId ? `profile: ${profileId}` : "";
  if (!ragPayload.rag_enabled) {
    els.ragPanel.innerHTML = `<p class="rag-note">${escapeHtml(
      ragPayload.reason || "RAG not enabled for this profile."
    )}</p>`;
    return;
  }
  if (ragPayload.error) {
    els.ragPanel.innerHTML = `<p class="rag-note is-error">${escapeHtml(ragPayload.error)}</p>`;
    return;
  }
  const staleClass = ragPayload.stale ? "is-warn" : "is-ok";
  const staleBadge = ragPayload.stale
    ? '<span class="badge badge-warn">stale</span>'
    : '<span class="badge badge-ok">current</span>';
  els.ragPanel.innerHTML = `
    <div class="rag-grid">
      <article class="stat-card"><span class="stat-label">Status</span><span class="stat-value">${staleBadge}</span></article>
      <article class="stat-card"><span class="stat-label">Files</span><span class="stat-value">${fmtNumber(ragPayload.indexed_files)}</span></article>
      <article class="stat-card"><span class="stat-label">Chunks</span><span class="stat-value">${fmtNumber(ragPayload.indexed_chunks)}</span></article>
      <article class="stat-card"><span class="stat-label">Embedding</span><span class="stat-value" style="font-size:12px">${escapeHtml(
        `${ragPayload.embedding_backend}/${ragPayload.embedding_model}`
      )}</span></article>
    </div>
    <p class="rag-note ${staleClass}">${escapeHtml(ragPayload.stale_reason || "Index state unknown.")}</p>
    <dl class="kv-list">
      <div><dt>index dir</dt><dd>${escapeHtml(ragPayload.index_dir || "—")}</dd></div>
      <div><dt>manifest</dt><dd>${ragPayload.manifest_exists ? "yes" : "no"}</dd></div>
      <div><dt>bm25</dt><dd>${ragPayload.bm25_exists ? "yes" : "no"}</dd></div>
      <div><dt>vector db</dt><dd>${ragPayload.vector_exists ? "yes" : "no"}</dd></div>
      <div><dt>dim</dt><dd>${escapeHtml(String(ragPayload.embedding_dim ?? "—"))}</dd></div>
    </dl>`;
}

function renderEndpoints() {
  els.endpointList.innerHTML = ENDPOINTS.map(
    (item) => `<li><span class="method">${item.method}</span><span><code>${escapeHtml(
      item.path
    )}</code> — ${escapeHtml(item.note)}</span></li>`
  ).join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadProfileDetail(profileId) {
  if (!profileId) {
    els.profileDetail.classList.add("hidden");
    return;
  }
  const profile = await fetchJson(`/api/profile?profile_id=${encodeURIComponent(profileId)}`);
  renderProfileDetail(profile);
  // /api/profile is intentionally cheap and no longer embeds rag_index; fetch
  // RAG health from the dedicated endpoint.
  const ragIndex = await fetchJson(`/api/rag/index?profile_id=${encodeURIComponent(profileId)}`);
  renderRag(ragIndex || {}, profileId);
}

async function refreshDashboard() {
  clearError();
  saveApiBase();
  const started = performance.now();
  try {
    const [status, models, profiles] = await Promise.all([
      fetchJson("/api/status"),
      fetchJson("/api/models"),
      fetchJson("/api/profiles"),
    ]);
    renderStatCards(status);
    renderLimits(status);
    renderBudget(status.budget);
    renderModels(models);
    renderProfiles(profiles);
    renderEndpoints();
    const profileId = els.profileSelect.value || state.defaultProfile;
    await loadProfileDetail(profileId);
    const ms = Math.round(performance.now() - started);
    els.loadMeta.textContent = `Updated ${new Date().toLocaleTimeString()} · ${apiBase()} · ${ms}ms`;
  } catch (err) {
    showError(err instanceof Error ? err.message : String(err));
    els.loadMeta.textContent = "";
  }
}

els.refreshBtn.addEventListener("click", () => {
  refreshDashboard();
});

els.apiBase.addEventListener("change", () => {
  refreshDashboard();
});

els.profileSelect.addEventListener("change", async () => {
  clearError();
  try {
    await loadProfileDetail(els.profileSelect.value);
  } catch (err) {
    showError(err instanceof Error ? err.message : String(err));
  }
});

loadApiBase();
renderEndpoints();
refreshDashboard();
