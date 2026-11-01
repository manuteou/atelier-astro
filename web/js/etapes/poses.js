// S3 : choix des poses à écarter, en trois niveaux (rejets nets, mitigées, proches de la limite), avec vignettes
// et une pose typique pour comparer. Les cases remplissent le champ « Poses à écarter » (source de vérité).
import { h, S, toast } from "../core.js";
import { initEditor } from "../editeur.js";
import { openViewer } from "../visionneuse.js";

const BLOCS = [
  ["nette", "Rejets nets", "écartées par défaut : fond au moins deux fois plus clair, presque plus d'étoiles, ou fond très inhabituel"],
  ["mitigee", "Mitigées", "à toi de décider : voile léger, début d'aube, nettement moins d'étoiles"],
  ["limite", "Proches de la limite", "gardées par défaut : fond un peu plus clair, étoiles moins nombreuses ou moins fines"],
];

function parseExcl(txt, groups) {
  const out = {};
  groups.forEach(g => { out[g.dev] = new Set(); });
  const s = String(txt || "");
  if (groups.length === 1 && !s.includes(":")) {
    s.split(/[,;\s]+/).filter(x => /^\d+$/.test(x)).forEach(x => out[groups[0].dev].add(x));
    return out;
  }
  for (const part of s.split(";")) {
    const [d, lst] = part.split(":");
    if (lst === undefined) continue;
    const dev = d.trim();
    if (!out[dev]) out[dev] = new Set();
    lst.split(/[,\s]+/).filter(x => /^\d+$/.test(x)).forEach(x => out[dev].add(x));
  }
  return out;
}
function formatExcl(sets, groups) {
  const sortN = (a) => [...a].sort((x, y) => x - y).join(",");
  if (groups.length === 1 && !groups[0].dev) return sortN(sets[""]);
  return groups.map(g => `${g.dev}: ${sortN(sets[g.dev] || [])}`).join(" ; ");
}

export function posePicker(step, onChange) {
  const groups = step.poses || [];
  const vals = initEditor(step)[0];
  const wrap = h("div", { class: "poses" });
  if (!groups.length || !groups.some(g => g.poses.length)) {
    wrap.append(h("div", { class: "banner info" }, "Le tri de l'étape précédente n'a signalé aucune pose, ni aucune proche de la limite : toutes les poses seront empilées."));
    return wrap;
  }
  let sets = parseExcl(vals.exclure, groups);
  const commit = () => { vals.exclure = formatExcl(sets, groups); onChange && onChange(); draw(); };
  const url = (g, fichier) => `/api/projects/${encodeURIComponent(S.project)}/pose?fichier=${fichier}&dev=${encodeURIComponent(g.dev)}`;
  const view = (g, fichier, title) => openViewer(step, { main: url(g, fichier), nointeract: true, absolute: true }, title);
  const body = h("div");
  const draw = () => {
    body.innerHTML = "";
    for (const g of groups) {
      if (!g.poses.length) continue;
      const set = sets[g.dev] || (sets[g.dev] = new Set());
      body.append(h("div", { class: "pose-head" }, g.dev ? h("b", {}, g.dev + " · ") : null, `${set.size} pose(s) écartée(s)`,
        g.reference ? h("button", { class: "linkbtn", onclick: () => view(g, g.reference.fichier, "Pose typique de la nuit") }, "voir la pose typique") : null));
      for (const [niv, titre, aide] of BLOCS) {
        const rows = g.poses.filter(r => r.niveau === niv);
        if (!rows.length) continue;
        const ids = rows.map(r => String(r[g.key]));
        const all = ids.every(id => set.has(id)), some = ids.some(id => set.has(id));
        const toggleAll = h("input", { type: "checkbox", checked: all, title: all ? "garder toutes ces poses" : "écarter toutes ces poses",
          onchange: (e) => { ids.forEach(id => e.target.checked ? set.add(id) : set.delete(id)); commit(); } });
        toggleAll.indeterminate = some && !all;
        const table = h("table", { class: "pose-table" },
          rows.map(r => {
            const id = String(r[g.key]);
            const out = set.has(id);
            return h("tr", { class: out ? "off" : "" },
              h("td", {}, h("input", { type: "checkbox", checked: out, title: out ? "écartée (décocher pour la garder)" : "gardée (cocher pour l'écarter)",
                onchange: (e) => { e.target.checked ? set.add(id) : set.delete(id); commit(); } })),
              h("td", { class: "mono" }, id),
              h("td", {}, r.raison || ""),
              h("td", { class: "muted mono" }, `fond x${(+r.rapport).toFixed(2)}`),
              h("td", { class: "muted mono" }, `${r.etoiles_pct} % ét.`),
              h("td", {}, h("button", { class: "linkbtn", onclick: () => view(g, r.fichier, `Pose ${id} (${titre.toLowerCase()})`) }, "voir")));
          }));
        body.append(h("details", { class: "pose-bloc niv-" + niv, open: niv !== "limite" },
          h("summary", {}, toggleAll, h("b", {}, ` ${titre}`), h("span", { class: "muted" }, ` (${rows.length}) — ${aide}`)), table));
      }
    }
  };
  wrap.append(h("div", { class: "pose-bar" }, h("b", {}, "Poses à écarter"),
    h("span", { class: "muted small" }, "cochée = écartée ; la case d'un bloc les coche ou décoche toutes ; « voir » ouvre l'image.")), body);
  draw();
  return wrap;
}
