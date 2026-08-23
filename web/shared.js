// Helpers shared by the three EasyAgent local pages: the technical dashboard
// (app.js), the eval dashboard (evals/evals.js), and the Agent Builder
// (builder/builder.js). Load this before the page script.
//
// These read `els` at call time, so each page script must declare its own
// top-level `els` with at least `apiBase` and `loadError` elements. All three
// pages deliberately share one API-base setting via API_BASE_KEY.

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);
const API_BASE_KEY = "easyagent-dashboard-api-base";

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
