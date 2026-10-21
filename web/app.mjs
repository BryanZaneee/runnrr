import {
  initProjects,
  projectState,
  workspaceHeaders,
  apiURL,
} from "./projects.mjs";
import { identityBadge } from "./identity.mjs";
import { renderTextBlock } from "./transcript.mjs";
import { readEvents, applyEvent, safeUrl } from "./chat.mjs";
import { turnUsage, threadUsage, usagePanel } from "./usage.mjs";
import {
  createThread,
  threadShelf,
  organizeThread,
  wakeThreads,
} from "./threads.mjs";

const $ = (id) => document.getElementById(id);
const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const icon = (name) => `<img src="/vendor/icons/${name}.svg" alt="">`;
const state = {
  profiles: [],
  profileId: null,
  models: [],
  model: null,
  sessions: [],
  activeId: null,
  details: new Map(),
  tools: [],
  connected: false,
  loading: true,
  panel: window.innerWidth > 1100 ? "home" : null,
  shelves: { snoozed: false, settled: false },
};
const profile = () => state.profiles.find((p) => p.id === state.profileId);
const active = () => state.sessions.find((s) => s.id === state.activeId);
const avatar = (p) => identityBadge(p, state.profiles);
const friendly = (name) =>
  ({
    list_kb: "Browse documents",
    read_file: "Read a document",
    search_kb: "Search documents",
    semantic_search_kb: "Find relevant knowledge",
    web_search: "Search the web",
    fetch_url_text: "Read a web page",
    calculator: "Calculate",
    read_skill: "Follow a saved skill",
    catalog_lookup: "Look up a product",
    qualify_lead: "Qualify a lead",
    lead_capture_preview: "Preview lead details",
    checkout_link_preview: "Preview checkout",
    get_resume_summary: "Read profile summary",
    get_project_context: "Read project context",
  })[name] || String(name).replaceAll("_", " ");
const panels = {
  usage: {
    title: "Usage & costs",
    icon: "cpu-chip",
    hint: "Tokens, caching, costs, and history",
  },
  assistants: {
    title: "Assistants",
    icon: "squares-2x2",
    hint: "Choose who you work with",
  },
  knowledge: {
    title: "Knowledge",
    icon: "document-text",
    hint: "Documents your assistant can use",
  },
  tools: {
    title: "Tools & skills",
    icon: "puzzle-piece",
    hint: "See what your assistant can do",
  },
  sources: {
    title: "Sources",
    icon: "link",
    hint: "References from this thread",
  },
  activity: {
    title: "Activity",
    icon: "bolt",
    hint: "Follow the work behind a response",
  },
  details: {
    title: "Thread details",
    icon: "information-circle",
    hint: "Model, messages, and usage",
  },
};

async function api(path, options = {}) {
  const res = await fetch(apiURL(path), {
    ...options,
    headers: {
      ...workspaceHeaders(),
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
    signal: AbortSignal.timeout(options.method ? 60000 : 12000),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "Could not load workspace data. Please reconnect.",
    );
  }
  return res.json();
}

function toast(message, undo = null) {
  $("toast-message").textContent = message;
  $("toast").hidden = false;
  $("undo-action").hidden = !undo;
  $("undo-action").onclick = () => {
    undo?.();
    $("toast").hidden = true;
  };
  clearTimeout(toast.timer);
  toast.timer = setTimeout(
    () => {
      $("toast").hidden = true;
    },
    undo ? 10000 : 4000,
  );
}

function setNavigation(open) {
  const mobile = window.innerWidth <= 760;
  $("sidebar").classList.toggle("is-open", open && mobile);
  document.body.classList.toggle("sidebar-collapsed", !open && !mobile);
  $("sidebar-backdrop").hidden = !(open && mobile);
  $("open-nav").setAttribute("aria-expanded", String(open));
  $("main").inert = open && mobile;
  if (open && mobile) $("close-nav").focus();
  else if (!open) $("open-nav").focus();
}

function closeMobileNavigation() {
  if (window.innerWidth <= 760) setNavigation(false);
}

function setPanel(panel) {
  state.panel = panel;
  renderPanel();
  if (panel === "usage") loadUsage();
  if (panel) $("close-panel").focus();
  else $("panel-toggle").focus();
}

const usageState = {
  data: null,
  error: null,
  loading: false,
  days: 30,
  model: "",
  profile: "",
  budget: null,
};
let usageRequest = 0;
async function loadUsage() {
  const request = ++usageRequest;
  usageState.loading = true;
  usageState.error = null;
  if (state.panel === "usage") renderPanel();
  const until = new Date(),
    since = new Date(until);
  since.setUTCDate(since.getUTCDate() - usageState.days + 1);
  const params = new URLSearchParams({
    since: since.toISOString().slice(0, 10),
    until: until.toISOString().slice(0, 10),
    model: usageState.model,
    profile: usageState.profile,
  });
  const [history, budget] = await Promise.allSettled([
    api(`/api/usage?${params}`),
    api("/api/budget"),
  ]);
  if (request !== usageRequest) return;
  usageState.loading = false;
  usageState.budget = budget.status === "fulfilled" ? budget.value : null;
  if (history.status === "fulfilled") usageState.data = history.value;
  else
    usageState.error = "Usage history could not be loaded. Try Refresh usage.";
  if (state.panel === "usage") renderPanel();
}

async function loadDetail(id) {
  if (state.details.has(id)) return;
  try {
    state.details.set(
      id,
      await api(`/api/profile?profile_id=${encodeURIComponent(id)}`),
    );
    if (state.profileId === id) {
      renderChat();
      renderPanel();
    }
  } catch (error) {
    if (state.profileId === id) toast(error.message);
  }
}

function newChat(projectId = active()?.projectId || null, force = false) {
  if (!profile()) return;
  let session =
    !force &&
    state.sessions.find(
      (s) =>
        (s.projectId || null) === projectId &&
        s.profileId === state.profileId &&
        s.model === state.model &&
        !s.turns.length &&
        !s.draft &&
        !s.settled &&
        !s.snoozedUntil,
    );
  if (!session) {
    session = createThread(state.profileId, state.model);
    session.projectId = projectId;
    state.sessions.unshift(session);
  }
  state.activeId = session.id;
  $("sidebar-search").value = "";
  closeMobileNavigation();
  render();
  $("composer-input").focus();
}

function selectThread(id) {
  const s = state.sessions.find((s) => s.id === id);
  if (!s) return;
  state.activeId = s.id;
  state.profileId = s.profileId;
  state.model = s.model;
  closeMobileNavigation();
  render();
  loadDetail(s.profileId);
}

function selectProfile(id) {
  if (!state.profiles.some((p) => p.id === id)) return;
  state.profileId = id;
  newChat();
  loadDetail(id);
}

function relativeTime(timestamp) {
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  return minutes < 1
    ? "now"
    : minutes < 60
      ? `${minutes}m`
      : minutes < 1440
        ? `${Math.floor(minutes / 60)}h`
        : `${Math.floor(minutes / 1440)}d`;
}

function threadRow(s, slim = false) {
  const p = state.profiles.find((p) => p.id === s.profileId),
    project = projectState.items.find((p) => p.id === s.projectId);
  const status = s.busy
    ? "Working"
    : s.failed
      ? "Needs attention"
      : s.turns.length
        ? "Done"
        : "Draft";
  const title =
    !s.turns.length && s.title === "New thread" && s.draft ? s.draft : s.title;
  const wake = s.snoozedUntil
    ? `Wakes ${new Date(s.snoozedUntil).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
    : "";
  return `<div class="thread-row ${slim ? "slim" : ""} ${s.id === state.activeId ? "selected" : ""}"><button class="thread-select" data-session="${s.id}" ${s.id === state.activeId ? 'aria-current="page"' : ""} aria-label="${escape(title)}, ${escape(p?.label)}, ${status}"><span class="thread-meta">${project ? identityBadge(project, projectState.items, "project") : avatar(p)}<span class="thread-agent">${escape(project?.name || p?.label || "Assistant")}</span><span class="thread-status ${s.busy ? "working" : s.failed ? "failed" : s.turns.length ? "done" : ""}">${s.busy ? icon("arrow-path") : s.turns.length && !s.failed ? icon("check") : ""}${s.busy || s.failed || s.turns.length ? status : relativeTime(s.updated)}</span></span><span class="thread-title">${escape(title)}</span><span class="thread-subtitle">${s.pinned ? icon("bookmark") : ""}${escape(wake || (project ? p?.label + " · " : "") + (state.models.find((m) => m.id === s.model)?.label || "Model not configured"))}</span></button><button class="thread-more icon-button" data-menu="${s.id}" aria-label="Actions for ${escape(title)}" title="Thread actions">${icon("ellipsis-horizontal")}</button></div>`;
}

function renderSidebar() {
  const query = $("sidebar-search").value.trim().toLowerCase();
  const sessions = state.sessions.filter((s) =>
    `${s.title} ${s.draft} ${projectState.items.find((p) => p.id === s.projectId)?.name || ""} ${state.profiles.find((p) => p.id === s.profileId)?.label || ""}`
      .toLowerCase()
      .includes(query),
  );
  $("new-chat").disabled = !profile();
  $("sidebar-list").innerHTML =
    ["pinned", "active"]
      .map((shelf) => {
        const items = sessions.filter((s) => threadShelf(s) === shelf);
        return items.length
          ? `${shelf === "pinned" ? '<p class="group-label">Pinned</p>' : ""}${items.map((s) => threadRow(s)).join("")}`
          : "";
      })
      .join("") ||
    `<p class="sidebar-empty">${query ? "No active threads match." : "A clear space for your next task."}</p>`;
  $("thread-shelves").innerHTML = ["snoozed", "settled"]
    .map((shelf) => {
      const items = sessions.filter((s) => threadShelf(s) === shelf);
      const open = state.shelves[shelf] || Boolean(query && items.length);
      return `<div class="shelf ${shelf}"><button class="shelf-toggle" data-shelf="${shelf}" aria-expanded="${open}" aria-controls="${shelf}-threads"><span>${shelf === "snoozed" ? "Snoozed" : "Settled"} <span class="shelf-count">${items.length}</span></span><span class="shelf-line"></span>${icon("chevron-down")}</button><div id="${shelf}-threads" class="shelf-list" ${open ? "" : "hidden"}>${items.map((s) => threadRow(s, true)).join("") || '<p class="sidebar-empty">Nothing here yet.</p>'}</div></div>`;
    })
    .join("");
}

function renderHeader() {
  const p = profile(),
    s = active();
  $("header-identity").innerHTML = `${
    s?.projectId
      ? `${identityBadge(
          projectState.items.find((p) => p.id === s.projectId),
          projectState.items,
          "project",
        )}<span class="breadcrumb-project">${escape(projectState.items.find((p) => p.id === s.projectId)?.name || "Project")}</span><span class="breadcrumb-divider">/</span>`
      : ""
  }${avatar(p)}<span class="breadcrumb-agent">${escape(p?.label || "Runnrr")}</span><span class="breadcrumb-divider">/</span><h1>${escape(s?.title || "New thread")}</h1>`;
  $("thread-actions").disabled = !s;
  $("runtime-status").textContent = state.loading
    ? "Connecting…"
    : !state.connected
      ? "Offline"
      : !state.model
        ? "Setup needed"
        : "Local workspace";
  $("runtime-status").classList.toggle(
    "offline",
    !state.connected || !state.model,
  );
}

function sourcesFor(session) {
  const sources = new Map();
  for (const t of session?.turns || [])
    for (const b of t.blocks) {
      for (const item of b.sources || [])
        sources.set(item.url || `${item.kind}:${item.label}`, item);
    }
  return [...sources.values()];
}

function sourceChip(item) {
  const label = escape(item.label || "Source"),
    url = safeUrl(item.url);
  return url
    ? `<a class="source-chip" href="${escape(url)}" target="_blank" rel="noopener noreferrer">${icon("link")}${label}</a>`
    : `<span class="source-chip">${icon("document-text")}${label}</span>`;
}

function empty(iconName, title, body) {
  return `<div class="empty-state">${icon(iconName)}<h3>${escape(title)}</h3><p>${escape(body)}</p></div>`;
}

function toolRow(b) {
  return `<div class="tool-row ${escape(b.status)}">${icon(b.status === "done" ? "check" : b.status === "error" ? "exclamation-triangle" : "arrow-path")}<span>${escape(friendly(b.name))}</span><span>${escape(b.status === "done" ? "Done" : b.status === "error" ? "Failed" : b.status === "running" ? "Working" : "Interrupted")}</span></div>${b.summary ? `<p class="source-summary">${escape(b.summary)}</p>` : ""}`;
}

function renderPanel() {
  const key = state.panel,
    p = profile(),
    s = active(),
    detail = state.details.get(state.profileId);
  $("workspace-panel").hidden = !key;
  $("panel-toggle").setAttribute("aria-expanded", String(Boolean(key)));
  $("panel-toggle").classList.toggle("selected", Boolean(key));
  $("chat-column").inert = Boolean(key) && window.innerWidth <= 1100;
  $("panel-title").textContent = panels[key]?.title || "Workspace";
  $("panel-home").disabled = key === "home";
  $("panel-resizer").setAttribute(
    "aria-valuenow",
    String(Math.round($("workspace-panel").getBoundingClientRect().width)),
  );
  if (!key) return;
  const root = $("panel-content"),
    sources = sourcesFor(s);
  root.classList.toggle("is-launcher", key === "home");
  if (key === "home") {
    root.innerHTML = `<div class="panel-launcher"><h3>Open a panel</h3>${Object.entries(
      panels,
    )
      .map(
        ([id, panel]) =>
          `<button data-panel="${id}" title="${panel.hint}">${icon(panel.icon)}<span>${panel.title}</span>${icon("chevron-right")}</button>`,
      )
      .join("")}</div>`;
  } else if (key === "usage") {
    root.innerHTML = usagePanel(usageState, state.models, state.profiles);
    $("usage-filters").onsubmit = (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      Object.assign(usageState, {
        days: Number(form.get("days")),
        model: form.get("model"),
        profile: form.get("profile"),
      });
      loadUsage();
    };
  } else if (key === "assistants") {
    root.innerHTML = `<div class="panel-intro"><p>Choose an assistant for a new thread.</p></div>${state.profiles.map((a) => `<button class="assistant-option ${a.id === state.profileId ? "selected" : ""}" data-profile="${escape(a.id)}">${avatar(a)}<span><strong>${escape(a.label)}</strong><span>${escape(a.description)}</span></span>${a.id === state.profileId ? icon("check") : ""}</button>`).join("")}${!state.profiles.length ? empty("squares-2x2", "No assistants configured", "Reconnect to load your assistants.") : '<p class="panel-note">Assistant creation and editing are not available yet.</p>'}`;
  } else if (key === "tools") {
    const tools = [
        ...(p?.tools || []),
        ...(s?.projectId ? ["search_project", "read_project_file"] : []),
      ],
      skills = detail?.skills || [];
    root.innerHTML = `<div class="panel-intro"><h3>${escape(p?.label || "Assistant")}</h3><p>Abilities available to this assistant.</p></div><p class="group-label">Tools · ${tools.length}</p>${tools.map((name) => `<details class="capability"><summary>${icon("puzzle-piece")}<span>${escape(friendly(name))}</span>${icon("chevron-down")}</summary><p>${escape(detail?.tool_schemas?.find((t) => t.name === name)?.description || state.tools.find((t) => t.name === name)?.description || "Available to this assistant.")}</p></details>`).join("")}<p class="group-label">Skills · ${skills.length}</p>${skills.map((skill) => `<details class="capability"><summary>${icon("document-text")}<span>${escape(skill.name)}</span>${icon("chevron-down")}</summary><p>${escape(skill.description)}</p></details>`).join("") || '<p class="panel-note">No saved skills for this assistant.</p>'}<p class="panel-note">These abilities are configured for the assistant. Editing them is not available yet.</p>`;
  } else if (key === "knowledge") {
    const project = projectState.items.find((p) => p.id === s?.projectId);
    const hasKnowledge =
      Boolean(project) ||
      (p?.tools || []).some((t) =>
        [
          "list_kb",
          "read_file",
          "search_kb",
          "semantic_search_kb",
          "get_resume_summary",
          "get_project_context",
        ].includes(t),
      );
    const documents = sources.filter((i) => !safeUrl(i.url));
    root.innerHTML = `${project ? `<div class="panel-intro"><h3>${escape(project.name)}</h3><p>${project.file_count} project files available to this assistant.</p><p>Updated ${escape(new Date(project.updated * 1000).toLocaleString())}</p></div>` : ""}<div class="panel-intro"><h3>${hasKnowledge ? "Your assistant’s knowledge" : "No documents connected"}</h3><p>${hasKnowledge ? "This assistant can consult its configured documents when you ask a question." : "This assistant currently works without a document collection."}</p></div>${documents.length ? `<p class="group-label">Referenced in this thread</p><div class="panel-sources">${documents.map(sourceChip).join("")}</div>` : empty("document-text", "No documents referenced yet", "Documents used in a response will appear here.")}<p class="panel-note">${projectState.mode === "portfolio" ? "Choose a portfolio project when starting a thread. Its public website and GitHub documents are ready to explore." : "Use Add project to import a folder of text files or a public GitHub repository."}</p>`;
  } else if (key === "sources") {
    root.innerHTML = sources.length
      ? `<div class="panel-intro"><p>References used in this conversation.</p></div><div class="panel-sources">${sources.map(sourceChip).join("")}</div>`
      : empty(
          "link",
          "Sources will appear here",
          "Ask a question. Links and document references will collect here as your assistant works.",
        );
  } else if (key === "activity") {
    const turns = (s?.turns || []).filter((t) =>
      t.blocks.some((b) => b.kind === "tool"),
    );
    root.innerHTML = turns.length
      ? turns
          .map(
            (t) =>
              `<section class="activity-group"><h3>${escape(t.prompt)}</h3>${t.blocks
                .filter((b) => b.kind === "tool")
                .map(toolRow)
                .join("")}</section>`,
          )
          .join("")
      : empty(
          "bolt",
          s?.busy ? "Your assistant is working" : "Nothing running right now",
          "Tool activity appears here when your assistant looks something up or takes an action.",
        );
  } else if (key === "details") {
    const tokens = (s?.turns || []).reduce((sum, t) => sum + t.tokens, 0);
    root.innerHTML = `<div class="panel-intro"><h3>${escape(s?.title || "New thread")}</h3><p>A little context for this conversation.</p></div><dl class="thread-details"><dt>Assistant</dt><dd>${escape(p?.label || "None")}</dd><dt>Model</dt><dd>${escape(state.models.find((m) => m.id === s?.model)?.label || "Not configured")}</dd><dt>Status</dt><dd>${s?.busy ? "Working" : s?.failed ? "Needs attention" : "Ready"}</dd><dt>Messages sent</dt><dd>${s?.turns.length || 0}</dd><dt>Tokens${s?.turns.some((t) => t.estimated) ? " (estimated)" : ""}</dt><dd>${tokens.toLocaleString()}</dd><dt>History</dt><dd>Temporary · this page only</dd></dl>${threadUsage(s?.turns || [])}<button class="panel-link" data-about>About temporary threads ${icon("chevron-right")}</button>`;
  }
}

let renderedThread = null;
const turnNodes = new WeakMap();
function renderChat() {
  const s = active(),
    pane = $("transcript");
  const changed = renderedThread !== s?.id;
  const atBottom =
    changed || pane.scrollHeight - pane.scrollTop - pane.clientHeight < 100;
  const oldScroll = pane.scrollTop;
  const expanded = new Set(
    [...pane.querySelectorAll("details[open]")].map((el) => el.dataset.turn),
  );
  if (!s?.turns.length) {
    const suggestions =
      state.details.get(state.profileId)?.suggestions?.slice(0, 3) || [];
    pane.innerHTML = `<div class="welcome"><span class="welcome-mark">${icon("bolt")}</span><h2>What would you like to get done?</h2><p>Start a conversation. Make a little room in your day.</p><div class="suggestions">${suggestions.map((text) => `<button data-suggestion="${escape(text)}">${icon("chat-bubble-left-right")}<span>${escape(text)}</span>${icon("chevron-right")}</button>`).join("")}</div></div>`;
  } else {
    const nodes = s.turns.map((turn, index) => {
      const cached = turnNodes.get(turn);
      if (
        turn.finished &&
        cached?.revision === turn.revision &&
        cached?.error === turn.error
      )
        return cached.node;
      const tools = turn.blocks.filter((b) => b.kind === "tool");
      const html = `<article class="turn"><div class="user-message">${escape(turn.prompt)}</div>${tools.length ? `<details class="work-details" data-turn="${index}" ${!changed && expanded.has(String(index)) ? "open" : ""}><summary>${turn.finished ? "Activity" : "Working"} · ${tools.length} ${tools.length === 1 ? "step" : "steps"} ${icon("chevron-right")}</summary><div>${tools.map(toolRow).join("")}</div></details>` : ""}<div class="assistant-message markdown">${turn.blocks
        .filter((b) => b.kind === "text")
        .map(renderTextBlock)
        .join(
          "",
        )}</div>${!turn.finished ? `<div class="activity">${icon("arrow-path")}<span>${turn.thinking ? "Thinking through your request…" : "Working on it…"}</span></div>` : ""}${turn.error ? `<div class="error-card" role="alert"><p>${escape(turn.error)}</p><p>Your partial response is kept here.</p><button data-fresh-chat>Start a fresh thread</button></div>` : ""}${turn.finished ? `<div class="turn-footer"><button class="icon-button" data-copy="${index}" aria-label="Copy response ${index + 1}" title="Copy response">${icon("clipboard")}</button>${turnUsage(turn, index, !changed && expanded.has(`usage-${index}`))}</div>` : ""}</article>`;
      const template = document.createElement("template");
      template.innerHTML = html;
      const node = template.content.firstElementChild;
      if (turn.finished)
        turnNodes.set(turn, {
          node,
          revision: turn.revision,
          error: turn.error,
        });
      return node;
    });
    if (changed || pane.firstElementChild?.classList.contains("welcome"))
      pane.replaceChildren(...nodes);
    else
      nodes.forEach((node, index) => {
        const existing = pane.children[index];
        if (existing === node) return;
        if (existing) existing.replaceWith(node);
        else pane.append(node);
      });
  }
  renderedThread = s?.id;
  pane.scrollTop = atBottom ? pane.scrollHeight : oldScroll;
  $("scroll-bottom").hidden =
    pane.scrollHeight - pane.scrollTop - pane.clientHeight < 150;
  renderComposer();
}

function renderComposer() {
  const s = active(),
    parked = s && ["snoozed", "settled"].includes(threadShelf(s));
  const missingProject =
    s?.projectId && !projectState.items.some((p) => p.id === s.projectId);
  const unavailable =
    missingProject ||
    state.loading ||
    !state.connected ||
    !s?.model ||
    !s ||
    s.busy ||
    s.failed ||
    parked;
  $("composer-input").disabled = Boolean(unavailable);
  $("composer-input").placeholder = s?.failed
    ? "Start a fresh thread to continue"
    : parked
      ? "Restore this thread to continue"
      : "What would you like to get done?";
  $("send-button").disabled = Boolean(unavailable || !s?.draft.trim());
  $("turn-status").textContent = s?.busy
    ? "Working…"
    : "Enter to send · Shift Enter for a new line";
  $("composer-context").innerHTML = missingProject
    ? "<span>This project is no longer available.</span><button data-fresh-chat>Start a new thread</button>"
    : parked
      ? `<span>This thread is ${s.snoozedUntil ? "snoozed" : "settled"}.</span><button data-organize="restore" data-thread="${s.id}">Restore thread</button>`
      : !s?.model && state.connected
        ? "No model provider is configured. Connect one in your runtime settings."
        : "";
}

function render() {
  renderSidebar();
  renderHeader();
  renderChat();
  renderPanel();
  $("assistant-select").innerHTML = state.profiles.length
    ? state.profiles
        .map(
          (p) => `<option value="${escape(p.id)}">${escape(p.label)}</option>`,
        )
        .join("")
    : "<option>No assistants</option>";
  $("assistant-select").value = state.profileId || "";
  $("assistant-select").disabled = !state.profiles.length;
  $("model-select").innerHTML = state.models.length
    ? state.models
        .map(
          (m) => `<option value="${escape(m.id)}">${escape(m.label)}</option>`,
        )
        .join("")
    : "<option>No model connected</option>";
  $("model-select").value = active()?.model || state.model || "";
  $("model-select").disabled = !state.models.length;
  $("composer-input").value = active()?.draft || "";
  resizeComposer();
}

let renderPending = false;
function streamRender() {
  if (renderPending) return;
  renderPending = true;
  requestAnimationFrame(() => {
    renderPending = false;
    renderHeader();
    renderChat();
    if (["activity", "sources", "details", "knowledge"].includes(state.panel))
      renderPanel();
  });
}

async function sendMessage() {
  const session = active();
  if (
    !session ||
    session.busy ||
    session.failed ||
    session.settled ||
    session.snoozedUntil ||
    !state.connected ||
    !session.model
  )
    return;
  const prompt = session.draft.trim();
  if (!prompt || prompt.length > 4000) return;
  if (!session.turns.length && session.title === "New thread")
    session.title = prompt.slice(0, 60);
  const turn = {
    prompt,
    blocks: [],
    tokens: 0,
    finished: false,
    thinking: false,
    error: null,
  };
  session.turns.push(turn);
  session.draft = "";
  session.busy = true;
  session.updated = Date.now();
  render();
  $("transcript").scrollTop = $("transcript").scrollHeight;
  try {
    const res = await fetch(apiURL("/api/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...workspaceHeaders() },
      body: JSON.stringify({
        session_id: session.id,
        message: prompt,
        model: session.model,
        profile: session.profileId,
        project_id: session.projectId || null,
      }),
    });
    if (!res.ok || !res.body) {
      const messages = {
        400: "The model or assistant is unavailable. Check the runtime configuration.",
        404: "This project is no longer available. Start a new thread.",
        409: "This thread is bound to a different project. Start a new thread.",
        429: "A chat or rate limit was reached. Wait a moment before starting a fresh thread.",
        503: "The runtime is at capacity or its daily budget is exhausted.",
      };
      throw new Error(
        messages[res.status] ||
          "The assistant could not start this request. Please try a fresh thread.",
      );
    }
    await readEvents(res.body, (event, data) => {
      applyEvent(turn, event, data);
      if (session.id === state.activeId) streamRender();
    });
    if (!turn.finished)
      throw new Error("The connection ended before the assistant finished.");
  } catch (error) {
    applyEvent(turn, "error", {
      message:
        error instanceof TypeError
          ? "The connection to the runtime was lost."
          : error.message,
    });
  } finally {
    session.busy = false;
    session.failed = Boolean(turn.error);
    if (state.panel === "usage") loadUsage();
    renderSidebar();
    renderHeader();
    if (session.id === state.activeId) {
      renderChat();
      renderPanel();
    }
  }
}

function advanceThread() {
  const next = state.sessions.find((s) => !s.settled && !s.snoozedUntil);
  if (next) selectThread(next.id);
  else newChat();
}

function organize(id, action, wakeAt = null) {
  const s = state.sessions.find((s) => s.id === id);
  if (!s) return;
  const previous = {
    pinned: s.pinned,
    settled: s.settled,
    snoozedUntil: s.snoozedUntil,
  };
  if (!organizeThread(s, action, wakeAt)) return;
  if (id === state.activeId && (action === "settle" || action === "snooze"))
    advanceThread();
  render();
  const label = {
    pin: s.pinned ? "Thread pinned" : "Thread unpinned",
    settle: "Thread settled",
    restore: "Thread restored",
    wake: "Thread awake",
    snooze: "Thread snoozed",
  }[action];
  toast(label, () => {
    Object.assign(s, previous);
    render();
  });
}

let menuThreadId = null;
function openThreadMenu(id, anchor) {
  const s = state.sessions.find((s) => s.id === id);
  if (!s) return;
  menuThreadId = id;
  const menu = $("thread-menu");
  menu.innerHTML = `<button data-rename>${icon("pencil-square")}Rename</button><button data-organize="pin" data-thread="${id}">${icon("bookmark")}${s.pinned ? "Unpin" : "Pin"} thread</button>${s.settled || s.snoozedUntil ? `<button data-organize="restore" data-thread="${id}">${icon("arrow-uturn-left")}${s.snoozedUntil ? "Wake" : "Restore"} thread</button>` : `<button data-organize="settle" data-thread="${id}" ${s.busy ? 'disabled title="Wait for this response to finish"' : ""}>${icon("archive-box")}Settle thread</button><div class="menu-label">Snooze for</div><button data-snooze="30">${icon("moon")}30 minutes</button><button data-snooze="60">${icon("clock")}1 hour</button><button data-snooze="1440">${icon("clock")}24 hours</button>`}<div class="menu-divider"></div><button data-delete ${s.busy ? 'disabled title="Wait for this response to finish"' : ""}>${icon("x-mark")}Delete thread</button>`;
  menu.showPopover();
  const box = anchor.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(box.left, window.innerWidth - menu.offsetWidth - 8))}px`;
  menu.style.top = `${Math.max(8, Math.min(box.bottom + 4, window.innerHeight - menu.offsetHeight - 8))}px`;
  menu.querySelector("button").focus();
}

async function connect() {
  if (connect.pending) return;
  connect.pending = true;
  state.loading = true;
  renderHeader();
  renderComposer();
  $("reconnect").disabled = true;
  try {
    await projectUI.load();
    const [health, profiles, models, tools] = await Promise.all([
      api("/api/health"),
      api("/api/profiles"),
      api("/api/models"),
      api("/api/tools"),
    ]);
    state.connected = health.status === "ok";
    state.profiles = profiles.profiles;
    state.models = models.models;
    state.tools = tools.tools;
    if (!state.models.some((m) => m.id === state.model))
      state.model = models.default;
    if (!state.profiles.some((p) => p.id === state.profileId))
      state.profileId =
        state.profiles.find((p) => p.id === profiles.default)?.id ||
        state.profiles[0]?.id ||
        null;
    $("connection-banner").hidden = Boolean(
      state.model && state.profiles.length,
    );
    $("connection-message").textContent = !state.profiles.length
      ? "No assistants are configured in this runtime."
      : "No model provider is configured. Connect one in your runtime settings.";
    if (!active() && profile()) newChat();
    // An empty thread created before provider setup can now use the configured model.
    if (active() && !active().model && !active().turns.length)
      active().model = state.model;
    state.details.clear();
    if (state.profileId) await loadDetail(state.profileId);
  } catch {
    state.connected = false;
    $("connection-banner").hidden = false;
    $("connection-message").textContent =
      "Cannot reach your runtime. Your open threads are still here.";
  } finally {
    state.loading = false;
    connect.pending = false;
    $("reconnect").disabled = false;
    render();
  }
}

function resizeComposer() {
  const input = $("composer-input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
}

function resizePanel(width) {
  const maximum = Math.min(570, $("main").clientWidth - 420);
  const clamped = Math.round(Math.max(280, Math.min(width, maximum)));
  $("workspace-panel").style.setProperty("--panel-width", `${clamped}px`);
  $("panel-resizer").setAttribute("aria-valuemax", String(maximum));
  $("panel-resizer").setAttribute("aria-valuenow", String(clamped));
}

$("panel-resizer").onpointerdown = (event) => {
  if (event.button !== 0) return;
  event.preventDefault();
  event.currentTarget.setPointerCapture(event.pointerId);
  document.body.classList.add("resizing");
};
$("panel-resizer").onpointermove = (event) => {
  if (event.currentTarget.hasPointerCapture(event.pointerId))
    resizePanel(window.innerWidth - event.clientX);
};
$("panel-resizer").onlostpointercapture = () =>
  document.body.classList.remove("resizing");
$("panel-resizer").onkeydown = (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const width = $("workspace-panel").getBoundingClientRect().width;
  resizePanel(
    event.key === "Home"
      ? 280
      : event.key === "End"
        ? 570
        : width + (event.key === "ArrowLeft" ? 10 : -10),
  );
};

$("new-chat").onclick = () => projectUI.openNewThread();
$("sidebar-search").oninput = renderSidebar;
$("open-nav").onclick = () => setNavigation(true);
$("close-nav").onclick = $("sidebar-backdrop").onclick = () =>
  setNavigation(false);
$("reconnect").onclick = connect;
$("panel-toggle").onclick = () => setPanel(state.panel ? null : "home");
$("close-panel").onclick = () => setPanel(null);
$("panel-home").onclick = () => setPanel("home");
$("settings-assistants").onclick = () => {
  $("settings-dialog").close();
  closeMobileNavigation();
  setPanel("assistants");
};
$("abilities-toggle").onclick = () => setPanel("tools");
$("session-info").onclick = () => $("info-dialog").showModal();
$("thread-actions").onclick = (event) =>
  openThreadMenu(state.activeId, event.currentTarget);
$("assistant-select").onchange = (event) => selectProfile(event.target.value);
$("model-select").onchange = (event) => {
  state.model = event.target.value;
  if (active() && !active().turns.length) {
    active().model = state.model;
    render();
  } else {
    newChat();
    toast("New thread started with your selected model.");
  }
};
$("composer-form").onsubmit = (event) => {
  event.preventDefault();
  sendMessage();
};
$("composer-input").oninput = (event) => {
  if (active()) active().draft = event.target.value;
  resizeComposer();
  renderComposer();
  renderSidebar();
};
$("composer-input").onkeydown = (event) => {
  if (
    event.key === "Enter" &&
    !event.shiftKey &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.isComposing
  ) {
    event.preventDefault();
    sendMessage();
  }
};
$("transcript").onscroll = () => {
  const p = $("transcript");
  $("scroll-bottom").hidden =
    p.scrollHeight - p.scrollTop - p.clientHeight < 150;
};
$("scroll-bottom").onclick = () => {
  $("transcript").scrollTop = $("transcript").scrollHeight;
};
$("rename-form").onsubmit = (event) => {
  event.preventDefault();
  const s = state.sessions.find((s) => s.id === menuThreadId),
    name = $("thread-name").value.trim();
  if (!s || !name) return;
  s.title = name;
  $("rename-dialog").close();
  render();
};
$("delete-form").onsubmit = (event) => {
  event.preventDefault();
  const index = state.sessions.findIndex((s) => s.id === menuThreadId),
    s = state.sessions[index];
  if (!s || s.busy) return;
  state.sessions.splice(index, 1);
  $("delete-dialog").close();
  if (state.activeId === s.id) advanceThread();
  render();
  toast("Thread deleted", () => {
    state.sessions.splice(index, 0, s);
    selectThread(s.id);
  });
};

window.addEventListener("resize", () => {
  $("sidebar").classList.remove("is-open");
  $("sidebar-backdrop").hidden = true;
  $("main").inert = false;
  $("open-nav").setAttribute(
    "aria-expanded",
    String(
      window.innerWidth > 760 &&
        !document.body.classList.contains("sidebar-collapsed"),
    ),
  );
  if (
    window.innerWidth > 1100 &&
    $("workspace-panel").style.getPropertyValue("--panel-width")
  )
    resizePanel($("workspace-panel").getBoundingClientRect().width);
  renderPanel();
  resizeComposer();
});
document.addEventListener("keydown", (event) => {
  if (document.querySelector("dialog[open]")) return;
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    setNavigation(true);
    $("sidebar-search").focus();
  }
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    projectUI.openNewThread();
  }
  if (event.key === "Escape") {
    if ($("thread-menu").matches(":popover-open")) return;
    if (state.panel && window.innerWidth <= 1100) setPanel(null);
    else if ($("sidebar").classList.contains("is-open")) setNavigation(false);
  }
  const trap =
    $("sidebar").classList.contains("is-open") && window.innerWidth <= 760
      ? $("sidebar")
      : state.panel && window.innerWidth <= 1100
        ? $("workspace-panel")
        : null;
  if (event.key === "Tab" && trap) {
    const controls = [
      ...trap.querySelectorAll("a,button,input,summary,select"),
    ].filter((el) => !el.disabled && el.getClientRects().length);
    const first = controls[0],
      last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  const d = button.dataset;
  if (d.profile) {
    selectProfile(d.profile);
    if (window.innerWidth <= 1100) setPanel(null);
  }
  if (d.session) selectThread(d.session);
  if (d.menu) openThreadMenu(d.menu, button);
  if (d.panel) setPanel(d.panel);
  if (d.shelf) {
    state.shelves[d.shelf] = !state.shelves[d.shelf];
    renderSidebar();
    $("thread-shelves").querySelector(`[data-shelf="${d.shelf}"]`).focus();
  }
  if (d.organize) {
    $("thread-menu").hidePopover();
    organize(d.thread, d.organize);
  }
  if (d.snooze) {
    $("thread-menu").hidePopover();
    organize(menuThreadId, "snooze", Date.now() + Number(d.snooze) * 60000);
  }
  if ("rename" in d) {
    $("thread-menu").hidePopover();
    $("thread-name").value =
      state.sessions.find((s) => s.id === menuThreadId)?.title || "";
    $("rename-dialog").showModal();
    $("thread-name").select();
  }
  if ("delete" in d) {
    $("thread-menu").hidePopover();
    $("delete-dialog").showModal();
  }
  if (d.closeDialog) $(d.closeDialog).close();
  if ("about" in d) $("info-dialog").showModal();
  if (d.suggestion && active() && !$("composer-input").disabled) {
    active().draft = d.suggestion;
    $("composer-input").value = d.suggestion;
    renderComposer();
    renderSidebar();
    resizeComposer();
    $("composer-input").focus();
  }
  if ("freshChat" in d) projectUI.openNewThread();
  if ("copy" in d) {
    const text = active()
      ?.turns[Number(d.copy)]?.blocks.filter((b) => b.kind === "text")
      .map((b) => b.text)
      .join("\n\n");
    if (!text) {
      toast("No response text to copy yet.");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      toast("Response copied");
    } catch {
      toast("Could not copy. Select the response text and copy it manually.");
    }
  }
});
setInterval(() => {
  if (wakeThreads(state.sessions)) {
    renderSidebar();
    renderComposer();
  }
}, 1000);
if (!/Mac|iPhone|iPad/.test(navigator.platform))
  $("search-shortcut").textContent = "Ctrl K";
const projectUI = initProjects({
  api,
  profiles: () => state.profiles,
  startThread: (id, projectId) => {
    state.profileId = id;
    newChat(projectId, true);
    loadDetail(id);
  },
  escape,
  icon,
  toast,
});
connect();
