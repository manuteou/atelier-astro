// Démarrage, liste des projets, ouverture d'un projet, navigation entre les étapes.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "./core.js";
import { dlgMateriel } from "./fenetres/materiel.js";
import { dlgNotes } from "./fenetres/notes.js";
import { dlgNewProject } from "./fenetres/nouveau_projet.js";
import { dlgPresets } from "./fenetres/presets.js";
import { dlgSettings } from "./fenetres/reglages.js";
import { renderMain } from "./page.js";
import { cancelJob, watchJob } from "./travaux.js";
import { closeViewer } from "./visionneuse.js";

// ------------------------------------------------------------------ démarrage
export async function init() {
  $("#btnNew").onclick = $("#btnNew2").onclick = () => dlgNewProject();
  $("#btnSettings").onclick = dlgSettings;
  $("#btnMateriel").onclick = () => dlgMateriel();
  $("#btnPresets").onclick = dlgPresets;
  $("#btnNotes").onclick = dlgNotes;
  $("#btnFolder").onclick = () => S.project && api("POST", `/api/projects/${S.project}/open`).catch(e => toast(e.message, true));
  $("#btnConsole").onclick = () => toggleConsole();
  $("#jobCancel").onclick = cancelJob;
  $("#dlgClose").onclick = closeDlg;
  $("#viewerClose").onclick = closeViewer;
  $("#projectSel").onchange = (e) => openProject(e.target.value);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeViewer(); closeDlg(); } });
  await loadConfig();
  api("GET", "/api/ollama").then(o => { S.ollama = o; if (S.data) renderMain(); }).catch(() => {});
  await loadProjects(localStorage.getItem("atelier.project"));
  reprendreSuivi();
}

/** Un traitement tourne déjà (page rechargée, ou autre onglet) : on reprend son suivi ici. */
async function reprendreSuivi() {
  const act = await api("GET", "/api/jobs?actifs=1").catch(() => []);
  if (!act.length || S.watch) return;
  const j = act.find(x => x.status === "en cours") || act[0];
  toast(`Traitement en cours repris : ${j.title}`);
  const fin = await watchJob(j.id);
  if (fin.status === "terminé" && S.project) await openProject(S.project, true);
}

export async function loadConfig() {
  const c = await api("GET", "/api/config");
  S.cfg = c;
  const p = $("#sirilPill");
  p.textContent = c.siril_ok ? (c.siril_version || "Siril prêt") : "Siril introuvable";
  p.className = "pill " + (c.siril_ok ? "ok" : "bad");
  p.title = c.config.siril_cli || "Renseigner siril-cli dans Réglages";
  if (!c.siril_ok) toast("siril-cli introuvable : ouvre Réglages pour indiquer son chemin.", true);
}

export async function loadProjects(select) {
  const list = await api("GET", "/api/projects");
  const sel = $("#projectSel");
  sel.innerHTML = "";
  sel.append(h("option", { value: "" }, list.length ? "— choisir un projet —" : "aucun projet"));
  for (const p of list) sel.append(h("option", { value: p.name }, `${p.target} · ${p.type} · ${p.done} étapes`));
  if (select && list.some(p => p.name === select)) { sel.value = select; await openProject(select); }
}

export async function openProject(name, keepStep = false) {
  if (!name) return;
  S.project = name;
  localStorage.setItem("atelier.project", name);
  S.data = await api("GET", `/api/projects/${encodeURIComponent(name)}`);
  S.bust = Date.now();
  $("#welcome")?.remove();
  const pr = S.data.state.preset;
  const b = $("#presetBadge");
  if (pr) { b.textContent = "Preset : " + pr.name; b.classList.remove("hidden"); } else b.classList.add("hidden");
  renderSteps();
  if (!keepStep || !S.sid) {
    const next = S.data.steps.find(s => s.applies && !["done", "skipped"].includes(s.state.status));
    S.sid = (next || S.data.steps[0]).id;
  }
  renderMain();
}

// ------------------------------------------------------------------ navigation
export function renderSteps() {
  const nav = $("#steps");
  nav.innerHTML = "";
  let phase = null;
  for (const s of S.data.steps) {
    if (s.phase !== phase) { phase = s.phase; nav.append(h("div", { class: "phase" }, phase)); }
    const st = s.state.status || "todo";
    nav.append(h("div", {
      class: "step" + (s.id === S.sid ? " on" : "") + (s.applies ? "" : " na"),
      title: s.applies ? (STATUS[st] || st) : s.why,
      onclick: () => { S.sid = s.id; S.applied = null; renderSteps(); renderMain(); },
    }, h("span", { class: "st " + st }), h("span", { class: "sid" }, s.id), h("span", {}, s.title)));
  }
}
