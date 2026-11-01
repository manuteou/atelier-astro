// Fenêtre « Matériel » : fiches des appareils.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";
import { pixels } from "../etapes/reglage_fin.js";
import { openProject } from "../projet.js";

export async function dlgMateriel() {
  let m;
  try { m = await api("GET", "/api/materiel" + (S.project ? `?project=${encodeURIComponent(S.project)}` : "")); } catch (e) { toast(e.message, true); return; }
  const body = h("div", {});
  const devs = Object.keys(m.profils);
  body.append(h("p", { class: "muted" }, "Le matériel est reconnu d'après les en-têtes des poses (instrument et focale). Ces fiches servent aux noms affichés, à l'alignement entre appareils (focale, pixels), au gain attendu (ouverture) et à la calibration des couleurs (capteur dans la base SPCC de Siril ; vide = calibration photométrique simple). Elles valent pour tous tes projets."));
  if (!devs.length) body.append(h("div", { class: "muted" }, S.project ? "Aucun appareil dans ce projet." : "Ouvre un projet pour voir son matériel."));
  const ins = {};
  for (const d of devs) {
    const p = m.profils[d];
    ins[d] = {};
    const card = h("div", { class: "vcard", style: "max-width:none;margin-bottom:10px" },
      h("h3", {}, p.nom || d, m.nouveaux.includes(d) ? h("span", { class: "pill small", style: "margin-left:8px" }, "nouveau : à vérifier") : null, h("span", { class: "spacer" }), h("span", { class: "muted mono small" }, d)));
    for (const [k, label, t] of m.champs) {
      let el;
      if (t === "choice") el = h("select", {}, m.corrections.map(([v, l]) => h("option", { value: v, selected: (p[k] || "aucune") === v }, l)));
      else el = h("input", { type: t === "float" ? "number" : "text", step: "any", value: p[k] ?? "" });
      ins[d][k] = el;
      card.append(h("div", { class: "field" }, h("label", {}, label), el));
    }
    body.append(card);
  }
  if (devs.length) body.append(h("div", { class: "actions" }, h("button", {
    onclick: async () => {
      const profils = Object.fromEntries(devs.map(d => [d, Object.fromEntries(Object.entries(ins[d]).map(([k, el]) => [k, el.value]))]));
      try { await api("POST", "/api/materiel", { profils }); closeDlg(); toast("Fiches du matériel enregistrées"); if (S.project) await openProject(S.project, true); }
      catch (e) { toast(e.message, true); }
    }
  }, "Enregistrer")));
  openDlg("Matériel", body);
}
