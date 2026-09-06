// Runnrr Agent Builder — no-code agent creation + a live "try it" chat pane.
// Talks to the gated /api/builder/* write API (runnrr/builder.py) plus the
// existing read-only /api/tools, /api/profiles, /api/models, /api/chat.

// Only these tools are shown to non-technical builders; everything else in
// the registry (semantic_search_kb, get_resume_summary, get_project_context)
// stays hidden.
const FRIENDLY_TOOLS = {
  list_kb: "See what's in its knowledge notes",
  read_file: "Read a knowledge note",
  search_kb: "Search its knowledge notes",
  web_search: "Search the internet",
  fetch_url_text: "Read a web page from a link",
  calculator: "Do math",
  catalog_lookup: "Look up items in a product catalog (demo)",
  qualify_lead: "Size up a sales lead (demo)",
  lead_capture_preview: "Collect contact details (demo — nothing is saved)",
  checkout_link_preview: "Show a checkout preview (demo — no real payments)",
};

const DEFAULT_NEW_TOOLS = ["list_kb", "read_file", "search_kb"];
const DEFAULT_ACCENT = "#386f3d";

const els = {
  agentSelect: document.getElementById("agent-select"),
  newAgentBtn: document.getElementById("new-agent-btn"),
  apiBase: document.getElementById("api-base"),
  loadError: document.getElementById("load-error"),
  disabledNotice: document.getElementById("disabled-notice"),
  builderBody: document.getElementById("builder-body"),
  tabSetupBtn: document.getElementById("tab-setup-btn"),
  tabKbBtn: document.getElementById("tab-kb-btn"),
  tabSetup: document.getElementById("tab-setup"),
  tabKb: document.getElementById("tab-kb"),
  tabSkillsBtn: document.getElementById("tab-skills-btn"),
  tabSkills: document.getElementById("tab-skills"),
  newSkillBtn: document.getElementById("new-skill-btn"),
  skillsList: document.getElementById("skills-list"),
  skillsEmpty: document.getElementById("skills-empty"),
  skillEmptyState: document.getElementById("skill-empty-state"),
  skillEditorWrap: document.getElementById("skill-editor-wrap"),
  skillName: document.getElementById("skill-name"),
  skillDescription: document.getElementById("skill-description"),
  skillSteps: document.getElementById("skill-steps"),
  saveSkillBtn: document.getElementById("save-skill-btn"),
  deleteSkillBtn: document.getElementById("delete-skill-btn"),
  skillStatus: document.getElementById("skill-status"),
  name: document.getElementById("f-name"),
  slugHint: document.getElementById("slug-hint"),
  description: document.getElementById("f-description"),
  instructions: document.getElementById("f-instructions"),
  welcome: document.getElementById("f-welcome"),
  suggestions: document.getElementById("f-suggestions"),
  abilitiesList: document.getElementById("abilities-list"),
  accent: document.getElementById("f-accent"),
  saveBtn: document.getElementById("save-btn"),
  saveStatus: document.getElementById("save-status"),
  newNoteBtn: document.getElementById("new-note-btn"),
  notesList: document.getElementById("notes-list"),
  kbEmpty: document.getElementById("kb-empty"),
  noteEmptyState: document.getElementById("note-empty-state"),
  noteEditorWrap: document.getElementById("note-editor-wrap"),
  notePathLabel: document.getElementById("note-path-label"),
  noteContent: document.getElementById("note-content"),
  saveNoteBtn: document.getElementById("save-note-btn"),
  deleteNoteBtn: document.getElementById("delete-note-btn"),
  noteStatus: document.getElementById("note-status"),
  chatResetBtn: document.getElementById("chat-reset-btn"),
  chatUnsaved: document.getElementById("chat-unsaved"),
  chatTranscript: document.getElementById("chat-transcript"),
  chatInput: document.getElementById("chat-input"),
  chatSendBtn: document.getElementById("chat-send-btn"),
};

let state = {
  toolsCatalog: [],
  defaultModel: "",
  agents: [],
  currentId: null,
  notes: [],
  selectedNotePath: null,
  skills: [],
  currentSkill: null,
  sessionId: crypto.randomUUID(),
  chatStreaming: false,
};

// ---------- API base (same localStorage pattern as web/app.js) ----------

function ownerToken() {
  let t = localStorage.getItem("runnrr-builder-owner");
  if (!t) {
    t = crypto.randomUUID();
    localStorage.setItem("runnrr-builder-owner", t);
  }
  return t;
}

async function apiFetch(path, options) {
  const base = apiBase();
  if (!base) {
    throw new Error("Set an API base URL (e.g. http://127.0.0.1:8001)");
  }
  const opts = { ...(options || {}) };
  if (path.startsWith("/api/builder/")) {
    opts.headers = { ...(opts.headers || {}), "X-Builder-Owner": ownerToken() };
  }
  const res = await fetch(`${base}${path}`, opts);
  let data = null;
  try {
    data = await res.json();
  } catch (err) {
    data = null;
  }
  return { status: res.status, ok: res.ok, data };
}

function extractDetail(data) {
  if (!data) return "";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map((d) => (d && d.msg) || JSON.stringify(d)).join("; ");
  }
  if (data.detail) return JSON.stringify(data.detail);
  return "";
}

function renderStatus(el, ok, message) {
  el.textContent = message;
  el.classList.remove("hidden", "is-ok", "is-error");
  el.classList.add(ok ? "is-ok" : "is-error");
}

function hideStatus(el) {
  el.classList.add("hidden");
  el.textContent = "";
}

function slugify(name) {
  let s = name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  if (!s) s = "agent";
  return s.slice(0, 64);
}

// ---------- Setup tab ----------

function updateSlugHint() {
  if (state.currentId) {
    els.slugHint.textContent = `saved as "${state.currentId}"`;
    return;
  }
  const name = els.name.value.trim();
  els.slugHint.textContent = name
    ? `will be saved as "${slugify(name)}"`
    : "Choose a name to see its saved id.";
}

function applyAccent(hex) {
  if (hex) {
    document.documentElement.style.setProperty("--chat-accent", hex);
  } else {
    document.documentElement.style.removeProperty("--chat-accent");
  }
}

function renderAbilities(selected) {
  const selectedSet = new Set(selected || []);
  const present = new Set(state.toolsCatalog.map((t) => t.name));
  els.abilitiesList.replaceChildren();
  Object.keys(FRIENDLY_TOOLS).forEach((name) => {
    if (!present.has(name)) return;
    const label = document.createElement("label");
    label.className = "ability-item";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = name;
    cb.checked = selectedSet.has(name);
    const span = document.createElement("span");
    span.textContent = FRIENDLY_TOOLS[name];
    label.appendChild(cb);
    label.appendChild(span);
    els.abilitiesList.appendChild(label);
  });
}

function getSelectedTools() {
  return Array.from(els.abilitiesList.querySelectorAll("input[type=checkbox]:checked")).map(
    (cb) => cb.value
  );
}

function populateForm(data) {
  els.name.value = data.label || "";
  els.description.value = data.description || "";
  els.instructions.value = data.instructions || "";
  els.welcome.value = data.welcome || "";
  els.suggestions.value = (data.suggestions || []).join("\n");
  els.accent.value = data.accent || DEFAULT_ACCENT;
  renderAbilities(data.tools || []);
  updateSlugHint();
  applyAccent(els.accent.value);
}

function startNewAgent() {
  state.currentId = null;
  els.name.value = "";
  els.description.value = "";
  els.instructions.value = "";
  els.welcome.value = "";
  els.suggestions.value = "";
  els.accent.value = DEFAULT_ACCENT;
  renderAbilities(DEFAULT_NEW_TOOLS);
  updateSlugHint();
  hideStatus(els.saveStatus);
  state.notes = [];
  state.selectedNotePath = null;
  hideNoteEditor();
  updateKbAvailability();
  els.chatTranscript.replaceChildren();
  updateChatAvailability();
  applyAccent(els.accent.value);
}

async function loadAgent(id) {
  const res = await apiFetch(`/api/builder/profile/${encodeURIComponent(id)}`);
  if (res.status !== 200) {
    showError(extractDetail(res.data) || `Could not load that agent (${res.status}).`);
    return;
  }
  state.currentId = id;
  populateForm(res.data);
  hideStatus(els.saveStatus);
  state.selectedNotePath = null;
  hideNoteEditor();
  updateKbAvailability();
  await loadNotes(id);
  els.chatTranscript.replaceChildren();
  updateChatAvailability();
}

async function handleSave() {
  const name = els.name.value.trim();
  if (!name) {
    renderStatus(els.saveStatus, false, "Give your agent a name first.");
    return;
  }
  const targetId = state.currentId || slugify(name);
  const suggestions = els.suggestions.value
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 8);
  const body = {
    label: name,
    description: els.description.value.trim(),
    instructions: els.instructions.value,
    welcome: els.welcome.value.trim(),
    suggestions,
    tools: getSelectedTools(),
    accent: els.accent.value || "",
  };

  els.saveBtn.disabled = true;
  try {
    const res = await apiFetch(`/api/builder/profile/${encodeURIComponent(targetId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.status === 200) {
      const wasNew = !state.currentId;
      state.currentId = (res.data && res.data.id) || targetId;
      renderStatus(els.saveStatus, true, "Saved — try it on the right!");
      updateSlugHint();
      state.sessionId = crypto.randomUUID();
      els.chatTranscript.replaceChildren();
      if (wasNew) {
        state.notes = [];
        state.selectedNotePath = null;
        hideNoteEditor();
      }
      updateKbAvailability();
      updateChatAvailability();
      await refreshAgentList(state.currentId);
      await loadNotes(state.currentId);
    } else {
      renderStatus(els.saveStatus, false, extractDetail(res.data) || `Save failed (${res.status}).`);
    }
  } catch (err) {
    renderStatus(els.saveStatus, false, err instanceof Error ? err.message : String(err));
  } finally {
    els.saveBtn.disabled = false;
  }
}

// ---------- Agent picker ----------

function renderAgentSelect() {
  els.agentSelect.replaceChildren();
  state.agents.forEach((a) => {
    const opt = document.createElement("option");
    opt.value = a.id;
    opt.textContent = a.editable ? `${a.label} (${a.id})` : `${a.label} (built-in example)`;
    if (!a.editable) opt.disabled = true;
    els.agentSelect.appendChild(opt);
  });
  const newOpt = document.createElement("option");
  newOpt.value = "__new__";
  newOpt.textContent = "+ New agent";
  els.agentSelect.appendChild(newOpt);
}

async function classifyAgents(profiles) {
  // `editable` used to be `probe.status === 200`, but read_profile deliberately
  // returns 200 for bundled profiles so they are readable as examples. Every
  // bundled profile therefore classified as editable, boot() loaded the first
  // one as the default target, and a new user's very first save 409'd. The
  // server already tells us: use its `readonly` flag.
  return Promise.all(
    profiles.map(async (p) => {
      const probe = await apiFetch(`/api/builder/profile/${encodeURIComponent(p.id)}`);
      if (probe.status !== 200) return { id: p.id, label: p.label, editable: false };
      const body = await probe.json().catch(() => ({}));
      return { id: p.id, label: p.label, editable: body.readonly === false };
    })
  );
}

async function refreshAgentList(selectId) {
  // Two sources: /api/profiles for the bundled read-only examples, and the
  // owner-scoped builder listing for agents this token created. The latter is
  // required because builder profiles are excluded from /api/profiles, so a
  // just-saved agent was invisible in the builder's own picker.
  const [profilesPayload, minePayload] = await Promise.all([
    apiFetch("/api/profiles"),
    apiFetch("/api/builder/profiles"),
  ]);
  const profiles = (profilesPayload.data && profilesPayload.data.profiles) || [];
  const mine = (minePayload.data && minePayload.data.profiles) || [];
  state.agents = [
    ...mine.map((p) => ({ id: p.id, label: p.label, editable: true })),
    ...(await classifyAgents(profiles)),
  ];
  renderAgentSelect();
  if (selectId && state.agents.some((a) => a.id === selectId)) {
    els.agentSelect.value = selectId;
  }
}

async function detectBuilderEnabled(profiles) {
  if (!profiles.length) return true;
  const probe = await apiFetch(`/api/builder/profile/${encodeURIComponent(profiles[0].id)}`);
  return probe.status !== 404;
}

// ---------- Knowledge tab ----------

function showNoteEditor() {
  els.noteEmptyState.classList.add("hidden");
  els.noteEditorWrap.classList.remove("hidden");
}

function hideNoteEditor() {
  els.noteEmptyState.classList.remove("hidden");
  els.noteEditorWrap.classList.add("hidden");
  els.notePathLabel.textContent = "";
  els.noteContent.value = "";
  hideStatus(els.noteStatus);
}

function updateKbAvailability() {
  const enabled = !!state.currentId;
  els.newNoteBtn.disabled = !enabled;
  if (!enabled) {
    state.notes = [];
    renderNotesList("Save your agent first, then add notes.");
  }
}

function renderNotesList(emptyMessageOverride) {
  els.notesList.replaceChildren();
  if (!state.notes.length) {
    els.kbEmpty.textContent =
      emptyMessageOverride || "Add notes your agent can read — menus, FAQs, policies, anything.";
    els.kbEmpty.classList.remove("hidden");
  } else {
    els.kbEmpty.classList.add("hidden");
  }
  state.notes.forEach((f) => {
    const li = document.createElement("li");
    li.textContent = f.path;
    if (f.path === state.selectedNotePath) li.classList.add("is-selected");
    li.addEventListener("click", () => selectNote(f.path));
    els.notesList.appendChild(li);
  });
}

async function loadNotes(id) {
  const res = await apiFetch(`/api/builder/kb/${encodeURIComponent(id)}`);
  state.notes = (res.data && res.data.files) || [];
  renderNotesList();
}

async function selectNote(path) {
  if (!state.currentId) return;
  try {
    const res = await apiFetch(
      `/api/builder/kb/${encodeURIComponent(state.currentId)}/file?path=${encodeURIComponent(path)}`
    );
    if (res.status !== 200) {
      renderStatus(els.noteStatus, false, extractDetail(res.data) || "Could not load that note.");
      return;
    }
    state.selectedNotePath = path;
    els.notePathLabel.textContent = path;
    els.noteContent.value = res.data.content || "";
    showNoteEditor();
    hideStatus(els.noteStatus);
    renderNotesList();
  } catch (err) {
    renderStatus(els.noteStatus, false, err instanceof Error ? err.message : String(err));
  }
}

async function handleSaveNote() {
  if (!state.currentId || !state.selectedNotePath) return;
  els.saveNoteBtn.disabled = true;
  try {
    const res = await apiFetch(`/api/builder/kb/${encodeURIComponent(state.currentId)}/file`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.selectedNotePath, content: els.noteContent.value }),
    });
    if (res.status === 200) {
      renderStatus(els.noteStatus, true, "Note saved.");
      await loadNotes(state.currentId);
    } else {
      renderStatus(els.noteStatus, false, extractDetail(res.data) || `Save failed (${res.status}).`);
    }
  } catch (err) {
    renderStatus(els.noteStatus, false, err instanceof Error ? err.message : String(err));
  } finally {
    els.saveNoteBtn.disabled = false;
  }
}

async function handleDeleteNote() {
  if (!state.currentId || !state.selectedNotePath) return;
  if (!window.confirm(`Delete "${state.selectedNotePath}"? This can't be undone.`)) return;
  els.deleteNoteBtn.disabled = true;
  try {
    const res = await apiFetch(
      `/api/builder/kb/${encodeURIComponent(state.currentId)}/file/delete`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: state.selectedNotePath }),
      }
    );
    if (res.status === 200) {
      state.selectedNotePath = null;
      hideNoteEditor();
      await loadNotes(state.currentId);
    } else {
      renderStatus(els.noteStatus, false, extractDetail(res.data) || `Delete failed (${res.status}).`);
    }
  } catch (err) {
    renderStatus(els.noteStatus, false, err instanceof Error ? err.message : String(err));
  } finally {
    els.deleteNoteBtn.disabled = false;
  }
}

function handleNewNote() {
  if (!state.currentId) return;
  const title = window.prompt("Note title (e.g. Menu, FAQ, Return policy)");
  if (!title) return;
  const path = `${slugify(title)}.md`;
  state.selectedNotePath = path;
  els.notePathLabel.textContent = path;
  els.noteContent.value = "";
  showNoteEditor();
  renderNotesList();
}

// ---------- Tabs ----------

const TABS = [
  ["setup", "tabSetupBtn", "tabSetup"],
  ["kb", "tabKbBtn", "tabKb"],
  ["skills", "tabSkillsBtn", "tabSkills"],
];

function switchTab(name) {
  for (const [id, btnKey, panelKey] of TABS) {
    const active = id === name;
    els[btnKey].classList.toggle("is-active", active);
    els[btnKey].setAttribute("aria-selected", String(active));
    els[panelKey].classList.toggle("hidden", !active);
  }
  if (name === "skills") refreshSkills();
}

// ---------- Skills tab ----------

function slugifySkill(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

function renderSkillsList() {
  els.skillsList.replaceChildren();
  els.skillsEmpty.classList.toggle("hidden", state.skills.length > 0);
  state.skills.forEach((s) => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = s.name || s.slug;
    btn.addEventListener("click", () => openSkill(s.slug));
    li.appendChild(btn);
    els.skillsList.appendChild(li);
  });
}

async function refreshSkills() {
  if (!state.currentId) {
    state.skills = [];
    renderSkillsList();
    return;
  }
  const res = await apiFetch(`/api/builder/skills/${encodeURIComponent(state.currentId)}`);
  state.skills = (res.data && res.data.skills) || [];
  renderSkillsList();
}

function showSkillEditor(show) {
  els.skillEditorWrap.classList.toggle("hidden", !show);
  els.skillEmptyState.classList.toggle("hidden", show);
}

function newSkill() {
  state.currentSkill = null;
  els.skillName.value = "";
  els.skillDescription.value = "";
  els.skillSteps.value = "";
  showSkillEditor(true);
  els.skillName.focus();
}

async function openSkill(slug) {
  const res = await apiFetch(
    `/api/builder/skills/${encodeURIComponent(state.currentId)}/one?slug=${encodeURIComponent(slug)}`
  );
  if (res.status !== 200) return;
  state.currentSkill = slug;
  els.skillName.value = res.data.name || "";
  els.skillDescription.value = res.data.description || "";
  els.skillSteps.value = res.data.steps || "";
  showSkillEditor(true);
}

async function saveSkill() {
  const name = els.skillName.value.trim();
  const description = els.skillDescription.value.trim();
  const steps = els.skillSteps.value.trim();
  if (!name || !description || !steps) {
    renderStatus(els.skillStatus, false, "Fill in all three boxes first.");
    return;
  }
  const slug = state.currentSkill || slugifySkill(name);
  if (!slug) {
    renderStatus(els.skillStatus, false, "Give the task a name using letters or numbers.");
    return;
  }
  const res = await apiFetch(`/api/builder/skills/${encodeURIComponent(state.currentId)}`, {
    method: "POST",
    body: { slug, name, description, steps },
  });
  if (res.status !== 200) {
    renderStatus(els.skillStatus, false, extractDetail(res.data) || `Save failed (${res.status}).`);
    return;
  }
  state.currentSkill = slug;
  renderStatus(els.skillStatus, true, "Saved — try it in the chat on the right!");
  refreshSkills();
}

async function deleteSkill() {
  if (!state.currentSkill) return;
  const res = await apiFetch(
    `/api/builder/skills/${encodeURIComponent(state.currentId)}/delete`,
    { method: "POST", body: { slug: state.currentSkill } }
  );
  if (res.status !== 200) {
    renderStatus(els.skillStatus, false, extractDetail(res.data) || `Delete failed (${res.status}).`);
    return;
  }
  state.currentSkill = null;
  showSkillEditor(false);
  refreshSkills();
}

// ---------- Try-it chat pane ----------

function scrollChatToBottom() {
  els.chatTranscript.scrollTop = els.chatTranscript.scrollHeight;
}

function appendChatBubble(kind, text) {
  const div = document.createElement("div");
  div.className = `chat-bubble is-${kind}`;
  div.textContent = text;
  els.chatTranscript.appendChild(div);
  scrollChatToBottom();
  return div;
}

function appendChatChip(text) {
  const div = document.createElement("div");
  div.className = "chat-chip";
  div.textContent = text;
  els.chatTranscript.appendChild(div);
  scrollChatToBottom();
}

function updateChatAvailability() {
  const enabled = !!state.currentId && !state.chatStreaming;
  els.chatInput.disabled = !enabled;
  els.chatSendBtn.disabled = !enabled;
  els.chatUnsaved.classList.toggle("hidden", !!state.currentId);
}

function handleSseFrame(frame, onDelta) {
  let eventType = "message";
  let dataLine = "";
  frame.split("\n").forEach((line) => {
    if (line.startsWith("event:")) eventType = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
  });
  if (!dataLine) return;
  let data;
  try {
    data = JSON.parse(dataLine);
  } catch (err) {
    return;
  }
  if (eventType === "delta") {
    onDelta(data.text || "");
  } else if (eventType === "tool_use_start") {
    appendChatChip(`using: ${FRIENDLY_TOOLS[data.name] || data.name}`);
  } else if (eventType === "error") {
    appendChatBubble("error", data.message || "Something went wrong.");
  }
  // thinking_delta, usage, tool_result, done are ignored in this pane.
}

async function sendChatMessage() {
  const text = els.chatInput.value.trim();
  if (!text || !state.currentId || state.chatStreaming) return;

  appendChatBubble("user", text);
  els.chatInput.value = "";
  state.chatStreaming = true;
  updateChatAvailability();

  // Created lazily on the first delta so tool chips appear above the reply.
  let agentBubble = null;
  let agentText = "";

  try {
    const res = await fetch(`${apiBase()}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        message: text,
        model: state.defaultModel,
        profile: state.currentId,
      }),
    });
    if (!res.ok || !res.body) {
      const errText = await res.text();
      appendChatBubble("error", `Something went wrong (${res.status}). ${errText.slice(0, 200)}`);
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        handleSseFrame(frame, (delta) => {
          if (!agentBubble) agentBubble = appendChatBubble("agent", "");
          agentText += delta;
          agentBubble.textContent = agentText;
          scrollChatToBottom();
        });
      }
    }
  } catch (err) {
    appendChatBubble("error", err instanceof Error ? err.message : String(err));
  } finally {
    state.chatStreaming = false;
    updateChatAvailability();
  }
}

function handleChatReset() {
  els.chatTranscript.replaceChildren();
  state.sessionId = crypto.randomUUID();
}

// ---------- Boot ----------

async function boot() {
  clearError();
  try {
    const [toolsPayload, modelsPayload, profilesPayload] = await Promise.all([
      apiFetch("/api/tools"),
      apiFetch("/api/models"),
      apiFetch("/api/profiles"),
    ]);
    state.toolsCatalog = (toolsPayload.data && toolsPayload.data.tools) || [];
    state.defaultModel = (modelsPayload.data && modelsPayload.data.default) || "";
    const profiles = (profilesPayload.data && profilesPayload.data.profiles) || [];

    const enabled = await detectBuilderEnabled(profiles);
    if (!enabled) {
      els.disabledNotice.classList.remove("hidden");
      els.builderBody.classList.add("hidden");
      return;
    }
    els.disabledNotice.classList.add("hidden");
    els.builderBody.classList.remove("hidden");

    state.agents = await classifyAgents(profiles);
    renderAgentSelect();

    const firstEditable = state.agents.find((a) => a.editable);
    if (firstEditable) {
      els.agentSelect.value = firstEditable.id;
      await loadAgent(firstEditable.id);
    } else {
      els.agentSelect.value = "__new__";
      startNewAgent();
    }
  } catch (err) {
    showError(err instanceof Error ? err.message : String(err));
  }
}

// ---------- Wiring ----------

els.apiBase.addEventListener("change", () => {
  saveApiBase();
  boot();
});

els.agentSelect.addEventListener("change", async () => {
  clearError();
  const val = els.agentSelect.value;
  if (val === "__new__") {
    startNewAgent();
    return;
  }
  try {
    await loadAgent(val);
  } catch (err) {
    showError(err instanceof Error ? err.message : String(err));
  }
});

els.newAgentBtn.addEventListener("click", () => {
  els.agentSelect.value = "__new__";
  startNewAgent();
});

els.name.addEventListener("input", updateSlugHint);
els.accent.addEventListener("input", () => applyAccent(els.accent.value));
els.saveBtn.addEventListener("click", handleSave);

els.tabSetupBtn.addEventListener("click", () => switchTab("setup"));
els.tabKbBtn.addEventListener("click", () => switchTab("kb"));
els.tabSkillsBtn.addEventListener("click", () => switchTab("skills"));
els.newSkillBtn.addEventListener("click", newSkill);
els.saveSkillBtn.addEventListener("click", saveSkill);
els.deleteSkillBtn.addEventListener("click", deleteSkill);

els.newNoteBtn.addEventListener("click", handleNewNote);
els.saveNoteBtn.addEventListener("click", handleSaveNote);
els.deleteNoteBtn.addEventListener("click", handleDeleteNote);

els.chatSendBtn.addEventListener("click", sendChatMessage);
els.chatInput.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) {
    ev.preventDefault();
    sendChatMessage();
  }
});
els.chatResetBtn.addEventListener("click", handleChatReset);

loadApiBase();
boot();
