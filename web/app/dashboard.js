import {
  apiFetch,
  getApiBase,
  getSupabase,
  requireSession,
  saveApiBase,
} from "./lib.js";

const els = {
  apiBase: document.getElementById("api-base"),
  userEmail: document.getElementById("user-email"),
  signOut: document.getElementById("sign-out"),
  loadError: document.getElementById("load-error"),
  templateSelect: document.getElementById("template-select"),
  agentLabel: document.getElementById("agent-label"),
  createAgent: document.getElementById("create-agent"),
  agentsBody: document.querySelector("#agents-table tbody"),
  usageRange: document.getElementById("usage-range"),
  usageStats: document.getElementById("usage-stats"),
  usageBars: document.getElementById("usage-bars"),
  usageModelsBody: document.querySelector("#usage-models-table tbody"),
};

function showError(message) {
  els.loadError.textContent = message;
  els.loadError.classList.remove("hidden");
}

function clearError() {
  els.loadError.textContent = "";
  els.loadError.classList.add("hidden");
}

function handleApiError(err) {
  if (err.status === 401) {
    window.location.href = "./login.html";
    return;
  }
  showError(err.message || String(err));
}

function renderTools(tools) {
  if (!tools?.length) return "0";
  if (tools.length <= 3) {
    return `<ul class="chip-list">${tools.map((t) => `<li><code>${t}</code></li>`).join("")}</ul>`;
  }
  return String(tools.length);
}

function renderAgents(agents) {
  els.agentsBody.innerHTML = agents
    .map(
      (a) => `
    <tr data-id="${a.id}">
      <td>${escapeHtml(a.label)}</td>
      <td><code>${escapeHtml(a.slug)}</code></td>
      <td>${renderTools(a.tools)}</td>
      <td><code>${escapeHtml(a.template_id || "")}</code></td>
      <td><button type="button" class="btn delete-agent">Delete</button></td>
    </tr>`,
    )
    .join("");
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function loadAgents() {
  const { agents } = await apiFetch("/api/agents");
  renderAgents(agents);
}

async function loadTemplates() {
  const { templates } = await apiFetch("/api/templates");
  els.templateSelect.innerHTML = templates
    .map((t) => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.label)}</option>`)
    .join("");
}

function renderUsage(data) {
  const cards = [
    ["Tokens total", data.tokens_total],
    ["Tokens in", data.tokens_in],
    ["Tokens out", data.tokens_out],
    ["Requests", data.requests],
  ];
  els.usageStats.innerHTML = cards
    .map(
      ([label, value]) => `
    <div class="stat-card">
      <span class="stat-label">${label}</span>
      <span class="stat-value">${Number(value).toLocaleString()}</span>
    </div>`,
    )
    .join("");

  const max = Math.max(1, ...data.per_day.map((d) => d.tokens_total));
  els.usageBars.innerHTML = data.per_day
    .map((d) => {
      const pct = Math.round((d.tokens_total / max) * 100);
      return `
      <div class="usage-bar-row">
        <span>${d.day.slice(5)}</span>
        <div class="budget-bar" aria-hidden="true"><span style="width:${pct}%"></span></div>
        <span>${d.tokens_total.toLocaleString()}</span>
      </div>`;
    })
    .join("");

  els.usageModelsBody.innerHTML = data.per_model
    .map(
      (m) => `
    <tr>
      <td><code>${escapeHtml(m.model)}</code></td>
      <td>${m.tokens_total.toLocaleString()}</td>
    </tr>`,
    )
    .join("");
}

async function loadUsage() {
  const range = els.usageRange.value;
  const data = await apiFetch(`/api/usage?range=${encodeURIComponent(range)}`);
  renderUsage(data);
}

async function init() {
  const session = await requireSession();
  if (!session) return;

  els.apiBase.value = getApiBase();
  els.userEmail.textContent = session.user?.email || "";

  els.apiBase.addEventListener("change", () => {
    saveApiBase(els.apiBase.value);
    window.location.reload();
  });

  els.signOut.addEventListener("click", async () => {
    const sb = await getSupabase();
    await sb.auth.signOut();
    window.location.href = "./login.html";
  });

  els.createAgent.addEventListener("click", async () => {
    clearError();
    try {
      const body = { template_id: els.templateSelect.value };
      const label = els.agentLabel.value.trim();
      if (label) body.label = label;
      await apiFetch("/api/agents", { method: "POST", body: JSON.stringify(body) });
      els.agentLabel.value = "";
      await loadAgents();
    } catch (err) {
      handleApiError(err);
    }
  });

  els.agentsBody.addEventListener("click", async (ev) => {
    const btn = ev.target.closest(".delete-agent");
    if (!btn) return;
    const row = btn.closest("tr");
    const id = row?.dataset.id;
    if (!id) return;
    clearError();
    try {
      await apiFetch(`/api/agents/${id}`, { method: "DELETE" });
      btn.replaceWith(Object.assign(document.createElement("span"), {
        className: "deleted-hint",
        textContent: "deleted",
      }));
      setTimeout(loadAgents, 600);
    } catch (err) {
      handleApiError(err);
    }
  });

  els.usageRange.addEventListener("change", () => {
    loadUsage().catch(handleApiError);
  });

  try {
    await Promise.all([loadTemplates(), loadAgents(), loadUsage()]);
  } catch (err) {
    handleApiError(err);
  }
}

init();
