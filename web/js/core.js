// Fondations : création d'éléments (h), appels à l'API, état partagé (S), messages, fenêtres.


export const $ = (s, el = document) => el.querySelector(s);

export const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "html") e.innerHTML = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
};

export const LETTERS = "ABCDEF";

export const STATUS = { todo: "à faire", essai: "essai non validé", done: "validé", stale: "à refaire (une étape précédente a changé)", skipped: "passée" };

export const S = { advice: {}, ollama: { ok: false, models: [] }, cfg: null, project: null, data: null, sid: null, edit: {}, job: null, logLen: 0, bust: Date.now() };

export async function api(method, url, body, timeoutMs = 0) {
  const ctl = timeoutMs ? new AbortController() : null;
  const t = ctl ? setTimeout(() => ctl.abort(), timeoutMs) : null;
  let r;
  try {
    r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined, signal: ctl?.signal });
  } catch (e) {
    throw new Error(e.name === "AbortError" ? "le serveur de l'appli ne répond pas" : "serveur de l'appli injoignable (fenêtre noire fermée ?)");
  } finally { if (t) clearTimeout(t); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

export function toast(msg, bad = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (bad ? " bad" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), bad ? 7000 : 3500);
}

export const fileUrl = (rel) => `/files/${encodeURIComponent(S.project)}/${rel}?t=${S.bust}`;

export function toggleConsole(open) {
  const c = $("#console");
  const willOpen = open === undefined ? c.classList.contains("collapsed") : open;
  c.classList.toggle("collapsed", !willOpen);
  document.body.classList.toggle("console-open", willOpen);
}

export const stepById = (sid) => S.data.steps.find(s => s.id === sid);

// ------------------------------------------------------------------ fenêtres
export function openDlg(title, body) { $("#dlgTitle").textContent = title; const b = $("#dlgBody"); b.innerHTML = ""; b.append(body); $("#dlg").classList.remove("hidden"); }

export function closeDlg() { $("#dlg").classList.add("hidden"); }

export const fmtSize = (b) => b >= 1e9 ? (b / 1e9).toFixed(2) + " Go" : b >= 1e6 ? (b / 1e6).toFixed(1) + " Mo" : Math.max(1, Math.round(b / 1e3)) + " Ko";
