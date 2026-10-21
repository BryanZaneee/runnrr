import { identityBadge } from "./identity.mjs";

// Only the workspace key persists in the browser; transcripts remain temporary.
let owner;
try {
  owner = localStorage.getItem("runnrr-workspace-key");
  if (!owner) {
    owner =
      crypto.randomUUID().replaceAll("-", "") +
      crypto.randomUUID().replaceAll("-", "");
    localStorage.setItem("runnrr-workspace-key", owner);
  }
} catch {
  owner = crypto.randomUUID().replaceAll("-", "");
}
export const workspaceHeaders = () => ({ "X-Workspace-Owner": owner });
export const apiURL = (path) =>
  (document.documentElement.dataset.apiBase || "/api") + path.slice(4);
export const projectState = { items: [], error: null, mode: "local" };

export function initProjects({
  api,
  profiles,
  startThread,
  escape,
  icon,
  toast,
}) {
  const $ = (id) => document.getElementById(id);
  const dialog = $("project-picker");
  let step = "agents",
    agent = null,
    selected = 0,
    files = {},
    saving = false,
    preferred = null,
    reading = false;
  async function load() {
    try {
      const result = await api("/api/projects");
      projectState.items = result.projects;
      projectState.mode = result.mode;
      projectState.error = null;
      $("add-project").hidden = result.mode === "portfolio";
    } catch (error) {
      projectState.error = error.message;
    }
  }
  function open(mode = "agents") {
    step = mode;
    selected = 0;
    $("picker-query").value = "";
    if (!dialog.open) dialog.showModal();
    render();
    $("picker-query").focus();
    load().then(() => {
      if (dialog.open) render();
    });
  }
  function render() {
    const q = $("picker-query").value.trim().toLowerCase();
    $("picker-back").hidden = step !== "projects";
    $("picker-heading").textContent =
      step === "agents"
        ? "Choose an assistant"
        : step === "projects"
          ? "Choose a project"
          : "Projects";
    const rows =
      step === "agents"
        ? profiles().map((p) => ({
            id: p.id,
            name: p.label,
            detail: p.description,
          }))
        : projectState.items.map((p) => ({
            id: p.id,
            name: p.name,
            detail: `${p.repository ? "GitHub · " + p.repository : (p.shared ? "Website · " : "Folder · ") + p.file_count + " files"} · ${p.shared ? "Shared" : "Your workspace"}`,
          }));
    const matches = rows.filter((p) =>
      `${p.name} ${p.detail}`.toLowerCase().includes(q),
    );
    $("picker-results").innerHTML =
      (step === "projects"
        ? `<button class="picker-option" data-choice=""><span class="project-avatar neutral">${icon("chat-bubble-left-right")}</span><span><strong>No project</strong><small>Start with just your assistant</small></span></button>`
        : "") +
      matches
        .map(
          (p) =>
            `<button class="picker-option" data-choice="${escape(p.id)}">${identityBadge(p, step === "agents" ? profiles() : projectState.items, step === "agents" ? "agent" : "project")}<span><strong>${escape(p.name)}</strong><small>${escape(p.detail)}</small></span></button>`,
        )
        .join("") +
      (!matches.length
        ? `<p class="picker-empty">${!projectState.items.length && step !== "agents" ? "No projects yet. Add a folder to get started." : "No matching results."}</p>`
        : "") +
      (step !== "agents" && projectState.mode !== "portfolio"
        ? `<button class="picker-option picker-add" data-picker-add>${icon("folder-plus")}<span>Add project</span></button>`
        : "") +
      (projectState.error && step !== "agents"
        ? `<p role="alert" class="picker-empty">${escape(projectState.error)}</p>`
        : "");
    mark(
      step === "projects" && preferred
        ? [...$("picker-results").querySelectorAll("button")].findIndex(
            (b) => b.dataset.choice === preferred,
          )
        : 0,
    );
  }
  function mark(index) {
    const choices = [...$("picker-results").querySelectorAll("button")];
    selected = Math.max(0, Math.min(index, choices.length - 1));
    choices.forEach((b, i) =>
      b.classList.toggle("highlighted", i === selected),
    );
    if (choices[selected])
      choices[selected].scrollIntoView({ block: "nearest" });
  }
  function details(id) {
    const p = projectState.items.find((p) => p.id === id);
    if (!p) return;
    $("picker-heading").textContent = p.name;
    $("picker-results").innerHTML =
      `<div class="project-detail"><p>${escape(p.repository || (p.shared ? "bryanzane.com" : "Uploaded folder"))} · ${p.file_count} files</p><p>Updated ${escape(new Date(p.updated * 1000).toLocaleString())}</p>${p.shared ? "<p>Portfolio knowledge refreshes daily from bryanzane.com and linked public GitHub repositories.</p>" : ""}<button class="primary-button" data-project-start="${escape(p.id)}">Start a thread</button>${p.editable && p.repository ? `<button data-project-refresh="${escape(p.id)}">Refresh from GitHub</button>` : ""}${p.editable ? `<button data-project-delete="${escape(p.id)}">Remove project</button>` : ""}<button data-project-list>Back to projects</button><p id="project-detail-status" role="status"></p></div>`;
  }
  dialog.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b || b.disabled) return;
    if ("pickerAdd" in b.dataset) {
      dialog.close();
      openAdd();
    }
    if ("choice" in b.dataset) {
      if (step === "agents") {
        agent = b.dataset.choice;
        step = "projects";
        $("picker-query").value = "";
        render();
        $("picker-query").focus();
      } else if (step === "projects") {
        dialog.close();
        startThread(agent, b.dataset.choice || null);
      } else details(b.dataset.choice);
    }
    if (b.dataset.projectStart) {
      preferred = b.dataset.projectStart;
      open("agents");
    }
    if ("projectList" in b.dataset) open("browse");
    if (b.dataset.projectRefresh || b.dataset.projectDelete) {
      const id = b.dataset.projectRefresh || b.dataset.projectDelete;
      if (
        b.dataset.projectDelete &&
        !confirm(
          "Remove this project and its stored files? Existing threads will need a new project.",
        )
      )
        return;
      b.disabled = true;
      try {
        await api(
          `/api/projects/${id}/${b.dataset.projectRefresh ? "refresh" : "delete"}`,
          { method: "POST" },
        );
        await load();
        open("browse");
        toast(
          b.dataset.projectRefresh ? "Project refreshed" : "Project removed",
        );
      } catch (error) {
        $("project-detail-status").textContent = error.message;
        b.disabled = false;
      }
    }
  });
  $("picker-query").oninput = render;
  $("picker-back").onclick = () => open("agents");
  dialog.addEventListener("keydown", (e) => {
    if (e.target !== $("picker-query")) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      mark(selected + (e.key === "ArrowDown" ? 1 : -1));
    }
    if (e.key === "Enter") {
      e.preventDefault();
      $("picker-results").querySelectorAll("button")[selected]?.click();
    }
  });
  function openAdd() {
    if (saving) return;
    files = {};
    $("add-project-form").reset();
    $("project-file-summary").textContent = "No files chosen.";
    $("project-create-error").hidden = true;
    $("add-project-dialog").showModal();
  }
  $("project-files").onchange = async (e) => {
    reading = true;
    $("project-save").disabled = true;
    files = {};
    let skipped = 0,
      total = 0;
    for (const file of e.target.files) {
      const name = file.webkitRelativePath || file.name;
      if (
        !/\.(md|txt|rst|py|js|mjs|ts|tsx|jsx|html|css|csv)$/i.test(name) ||
        name
          .split("/")
          .some(
            (s) => s.startsWith(".") || ["node_modules", "vendor"].includes(s),
          ) ||
        file.size > 200000
      ) {
        skipped++;
        continue;
      }
      if (Object.keys(files).length >= 80 || total + file.size > 1000000) {
        skipped++;
        continue;
      }
      let text;
      try {
        text = await file.text();
      } catch {
        skipped++;
        continue;
      }
      if (text.includes("\0")) {
        skipped++;
        continue;
      }
      files[name] = text;
      total += file.size;
    }
    $("project-file-summary").textContent =
      `${Object.keys(files).length} files selected${skipped ? `, ${skipped} skipped` : ""}.`;
    if (!$("project-name").value && e.target.files.length)
      $("project-name").value = (
        e.target.files[0].webkitRelativePath || "My project"
      ).split("/")[0];
    $("project-repository").value = "";
    reading = false;
    $("project-save").disabled = false;
  };
  $("add-project-form").onsubmit = async (e) => {
    e.preventDefault();
    if (saving || reading) return;
    saving = true;
    $("project-save").disabled = true;
    $("project-save").textContent = "Adding…";
    $("project-create-error").hidden = true;
    try {
      let repository = $("project-repository")
        .value.trim()
        .replace(/^github\.com\//, "https://github.com/");
      if (!repository && !Object.keys(files).length)
        throw new Error(
          "Add a public GitHub repository or choose a folder of text files.",
        );
      await api("/api/projects", {
        method: "POST",
        body: JSON.stringify({
          name: $("project-name").value.trim(),
          repository: repository || null,
          documents: repository ? {} : files,
        }),
      });
      await load();
      $("add-project-dialog").close();
      open("browse");
      toast("Project added. Choose it when starting a thread.");
    } catch (error) {
      $("project-create-error").textContent = error.message;
      $("project-create-error").hidden = false;
    } finally {
      saving = false;
      $("project-save").disabled = false;
      $("project-save").textContent = "Add project";
    }
  };
  $("add-project-dialog").addEventListener("cancel", (e) => {
    if (saving) e.preventDefault();
  });
  $("search-projects").onclick = () => open("browse");
  $("add-project").onclick = openAdd;
  $("workspace-settings").onclick = () => $("settings-dialog").showModal();
  $("manage-projects").onclick = () => {
    $("settings-dialog").close();
    open("browse");
  };
  return {
    openNewThread: () => {
      preferred = null;
      open("agents");
    },
    load,
  };
}
