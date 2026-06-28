import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js/+esm";

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);
const API_BASE_KEY = "easyagent-app-api-base";

let supabasePromise = null;
let supabaseClient = null;

export function getApiBase() {
  const stored = localStorage.getItem(API_BASE_KEY);
  if (stored !== null && stored.trim() !== "") {
    return stored.trim().replace(/\/$/, "");
  }
  return LOCAL_HOSTS.has(window.location.hostname) ? "http://127.0.0.1:8001" : "";
}

export function saveApiBase(value) {
  localStorage.setItem(API_BASE_KEY, (value || "").trim().replace(/\/$/, ""));
}

async function initSupabase() {
  if (supabaseClient) return supabaseClient;
  if (!supabasePromise) {
    supabasePromise = (async () => {
      const base = getApiBase();
      const url = `${base || ""}/api/public-config`;
      const res = await fetch(url);
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`public-config → ${res.status} ${detail.slice(0, 180)}`);
      }
      const cfg = await res.json();
      supabaseClient = createClient(cfg.supabase_url, cfg.supabase_anon_key);
      return supabaseClient;
    })();
  }
  return supabasePromise;
}

export async function getSupabase() {
  return initSupabase();
}

export async function getSession() {
  const sb = await getSupabase();
  const { data } = await sb.auth.getSession();
  return data.session;
}

export async function apiFetch(path, opts = {}) {
  const session = await getSession();
  const base = getApiBase();
  const headers = {
    "Content-Type": "application/json",
    ...(opts.headers || {}),
  };
  if (session?.access_token) {
    headers.Authorization = `Bearer ${session.access_token}`;
  }
  const res = await fetch(`${base}${path}`, { ...opts, headers });
  if (!res.ok) {
    const body = await res.text();
    const err = new Error(`${res.status} ${body.slice(0, 180)}`);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function requireSession() {
  const session = await getSession();
  if (!session) {
    window.location.href = "./login.html";
    return null;
  }
  return session;
}
