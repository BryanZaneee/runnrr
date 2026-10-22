const key = "runnrr-disabled-tools-v1";
let disabled = new Set();
try {
  const saved = JSON.parse(localStorage.getItem(key) || "[]");
  if (Array.isArray(saved))
    disabled = new Set(saved.filter((x) => typeof x === "string"));
} catch {
  /* Preferences remain available for this visit. */
}
export const disabledTools = () => [...disabled];
export function setToolEnabled(name, enabled) {
  if (enabled) disabled.delete(name);
  else disabled.add(name);
  try {
    localStorage.setItem(key, JSON.stringify([...disabled]));
  } catch {
    /* Visit-only preference. */
  }
}
const labels = {
  web_search: "Web search",
  fetch_url_text: "Read web pages",
  search_kb: "Exact search",
  semantic_search_kb: "Semantic search + embeddings",
  read_file: "Read documents",
  list_kb: "Browse documents",
  search_project: "Search project",
  read_project_file: "Read project files",
  calculator: "Calculator",
  read_skill: "Saved instructions",
  get_resume_summary: "Résumé summary",
  get_project_context: "Project context",
};
const retrieval = [
  "web_search",
  "fetch_url_text",
  "search_kb",
  "semantic_search_kb",
  "read_file",
  "list_kb",
  "search_project",
  "read_project_file",
];
const general = ["calculator", "read_skill"];
const escape = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const presentation = {
  web_search: ["magnifying-glass", "Search the live web"],
  fetch_url_text: ["link", "Open a public page"],
  search_kb: ["magnifying-glass", "Match words and phrases"],
  semantic_search_kb: ["cpu-chip", "Find related ideas"],
  read_file: ["document-text", "Read full source passages"],
  list_kb: ["folder", "Explore your knowledge library"],
  search_project: ["magnifying-glass", "Find answers in projects"],
  read_project_file: ["document-text", "Open project documents"],
  calculator: ["squares-2x2", "Run precise calculations"],
  read_skill: ["bookmark", "Follow saved procedures"],
  get_resume_summary: ["document-text", "Experience at a glance"],
  get_project_context: ["folder", "Background on your work"],
};
export function toolSettingsPanel(available, catalog, skills, busy) {
  const allowed = new Set(available);
  const row = (name) => {
    const setup = name === "web_search" && !allowed.has(name);
    const [icon, hint] = presentation[name] || [
      "puzzle-piece",
      "Assistant-specific action",
    ];
    const title = labels[name] || name.replaceAll("_", " ");
    const image = new URL(`../vendor/icons/${icon}.svg`, import.meta.url).href;
    const content = `<span class="tool-control-icon"><img src="${escape(image)}" alt=""></span><span class="tool-control-copy"><span class="tool-control-name">${escape(title)}</span><span class="tool-control-hint">${setup ? "Connect your search provider" : hint}</span></span>`;
    return setup
      ? `<div class="tool-control-row">${content}<button class="tool-setup-button" type="button" data-tool-setup="web_search" aria-label="Set up web search">Set up <span aria-hidden="true">↗</span></button></div>`
      : `<label class="tool-control-row">${content}<input class="tool-control-switch" type="checkbox" role="switch" aria-label="${escape(title)}" data-tool-setting="${escape(name)}" ${!disabled.has(name) ? "checked" : ""} ${busy ? "disabled" : ""}></label>`;
  };
  const section = (title, names) => {
    const active = names.filter(
      (name) => allowed.has(name) || name === "web_search",
    );
    return active.length
      ? `<section class="tool-control-section" aria-label="${title}"><div class="tool-control-heading"><h3>${title}</h3><span>${active.length}</span></div><div class="tool-control-list">${active.map(row).join("")}</div></section>`
      : "";
  };
  const custom = [...allowed].filter(
    (name) => !retrieval.includes(name) && !general.includes(name),
  );
  return `<div class="tool-controls">${section("Retrieval (RAG)", retrieval)}${section("Other tools", general)}${section("Custom tools", custom)}</div>`;
}

export function openToolSetup() {
  document.getElementById("settings-dialog")?.close();
  let dialog = document.getElementById("tool-setup-dialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "tool-setup-dialog";
    dialog.setAttribute("aria-labelledby", "tool-setup-title");
    dialog.innerHTML = `<h2 id="tool-setup-title">Web search setup</h2><p>Web search uses a Tavily API key.</p><p><a href="https://app.tavily.com/" target="_blank" rel="noopener noreferrer">Get an API key</a></p><p>The owner of this Runnrr server needs to connect it. This public interface does not save API keys.</p><details><summary>Server setup</summary><p>Add TAVILY_API_KEY to the server environment, configure reviewed Tavily request-cost bounds, enable web_search for the assistant, and restart Runnrr.</p></details><div class="dialog-actions"><button type="button" class="primary-button" data-close-tool-setup>Done</button></div>`;
    dialog.querySelector("[data-close-tool-setup]").onclick = () =>
      dialog.close();
    document.body.append(dialog);
  }
  dialog.showModal();
}
if (typeof document !== "undefined") {
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = new URL(
    "../css/tool-settings.css?v=20261022",
    import.meta.url,
  ).href;
  document.head.append(stylesheet);
  const settings = document.getElementById("settings-dialog");
  if (settings && !settings.querySelector("[data-tool-setup]")) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "settings-row";
    button.dataset.toolSetup = "web_search";
    button.textContent = "Web search API key";
    settings.insertBefore(button, settings.querySelector(".dialog-actions"));
  }
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-tool-setup]")) openToolSetup();
  });
}
