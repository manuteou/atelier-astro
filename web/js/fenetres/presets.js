// Fenêtre « Presets ».
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";
import { openProject } from "../projet.js";

export async function dlgPresets() {
  const list = await api("GET", "/api/presets");
  const body = h("div", {});
  body.append(h("p", { class: "muted" }, "Un preset pré-remplit les réglages des étapes de rendu (étirement, étoiles, couleurs, débruitage…). Il ne lance rien : chaque étape garde ses aperçus et ta validation. Le cadrage, les retouches et la fiche ne sont jamais enregistrés."));
  const pl = h("div", { class: "plist" });
  if (!list.length) pl.append(h("div", { class: "muted" }, "Aucun preset pour l'instant."));
  for (const p of list) pl.append(h("div", { class: "item" },
    h("div", { class: "grow" }, h("b", {}, p.name), h("span", { class: "muted" }, ` · ${p.type} · ${p.steps.length} étapes`), p.description ? h("div", { class: "muted" }, p.description) : null),
    S.project ? h("button", { onclick: async () => { await api("POST", `/api/projects/${S.project}/preset/apply`, { file: p.file }); S.edit = {}; closeDlg(); await openProject(S.project, true); toast("Preset appliqué aux réglages"); } }, "Appliquer") : null,
    h("button", { class: "danger small", onclick: async () => { if (confirm(`Supprimer le preset « ${p.name} » ?`)) { await api("DELETE", `/api/presets/${p.file}`); dlgPresets(); } } }, "Supprimer")));
  body.append(pl);
  if (S.project) {
    if (S.data.state.preset) body.append(h("div", { class: "actions" }, h("button", { class: "ghost", onclick: async () => { await api("POST", `/api/projects/${S.project}/preset/clear`); S.edit = {}; closeDlg(); await openProject(S.project, true); } }, "Retirer le preset de ce projet")));
    const name = h("input", { type: "text", placeholder: "ex. Nébuleuse sans étoiles fond noir" });
    const desc = h("input", { type: "text", placeholder: "description (facultatif)" });
    body.append(h("h3", {}, "Enregistrer les réglages validés de ce projet"),
      h("div", { class: "field" }, h("label", {}, "Nom"), name), h("div", { class: "field" }, h("label", {}, "Description"), desc),
      h("div", { class: "actions" }, h("button", { onclick: async () => { try { await api("POST", `/api/projects/${S.project}/preset/save`, { name: name.value, description: desc.value }); toast("Preset enregistré"); dlgPresets(); } catch (e) { toast(e.message, true); } } }, "Enregistrer le preset")));
  }
  openDlg("Presets", body);
}
