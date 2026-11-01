// P13 : marques « d'après tes données » / « brouillon Ollama » et brouillon des textes.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";
import { initEditor } from "../editeur.js";
import { renderMain } from "../page.js";
import { openProject } from "../projet.js";
import { waitJob } from "../travaux.js";

export const FICHE_AUTO = ["nom_technique", "lieu", "contexte", "visibilite", "intro_brut", "intro_finales"];

export function ficheMark(step, vals, name) {
  const m = S.ficheMarks?.[name];
  if (m && vals[name] === m.value) return m.from;
  if (FICHE_AUTO.includes(name) && vals[name] && vals[name] === step.dyn?.[name] && !S.data.state.fiche?.[name]) return "données";
  return null;
}

// ------------------------------------------------------------------ fiche : brouillon Ollama
export function fillFiche(step, fields, model, replaceAll) {
  const vals = initEditor(step)[0];
  S.ficheMarks = S.ficheMarks || {};
  const filled = [], kept = [];
  for (const [k, v] of Object.entries(fields || {})) {
    if (!v) continue;
    if (vals[k] && !replaceAll && S.ficheMarks[k]?.value !== vals[k]) { kept.push(k); continue; }
    vals[k] = v; S.ficheMarks[k] = { value: v, from: model }; filled.push(k);
  }
  const nt = vals.nom_technique;
  if (nt) for (const k of ["contexte", "visibilite"])        // textes automatiques écrits avant de connaître le nom
    if (vals[k]) vals[k] = vals[k].replace(/^Cet objet /, nt + " ").replace(/, cet objet /, `, ${nt} `);
  S.ficheKept = kept.length ? { fields, model } : null;
  return { filled, kept };
}

// Textes d'histoire : la voie fiable est Claude avec recherche web (faits sourcés), la réponse JSON se colle ici.
// Les modèles locaux testés (qwen2.5:7b, bonsai-2:27b) se trompaient sur la plupart des faits : brouillon seulement.
function claudeBox(step) {
  const answer = h("textarea", { placeholder: "Colle ici la réponse de Claude (le texte entier convient : l'objet JSON à la fin est repéré tout seul)", style: "min-height:70px;width:100%;margin-top:6px" });
  const copy = async () => {
    try {
      const r = await api("GET", `/api/projects/${S.project}/fiche/prompt`);
      await navigator.clipboard.writeText(r.text);
      toast("Demande copiée : colle-la dans une conversation avec Claude (recherche web activée)");
    } catch (e) { toast(e.message, true); }
  };
  const fill = async () => {
    try {
      const r = await api("POST", `/api/projects/${S.project}/fiche/answer`, { text: answer.value });
      const { filled, kept } = fillFiche(step, r.fields, "Claude", false);
      toast(`${filled.length} champ(s) remplis par la réponse de Claude` + (kept.length ? `, ${kept.length} déjà rempli(s) gardé(s)` : ""));
      renderMain();
    } catch (e) { toast(e.message, true); }
  };
  return h("div", { class: "banner info" },
    h("b", {}, "Textes vérifiés (recommandé)"),
    " : copie la demande, colle-la dans une conversation avec Claude (recherche web activée) : il cherche et vérifie les faits, avec ses sources. Colle ensuite sa réponse ci-dessous.",
    h("div", { class: "actions", style: "margin:8px 0 0" },
      h("button", { onclick: copy }, "Copier la demande pour Claude"),
      h("button", { class: "ghost", onclick: fill }, "Remplir la fiche avec la réponse")),
    answer);
}

export function ficheTools(step) {
  const wrap = h("div", {}, claudeBox(step));
  wrap.append(ollamaBox(step));
  return wrap;
}

function ollamaBox(step) {
  const lab = Object.fromEntries(step.params.map(p => [p.name, p.label]));
  const prev = S.data.state.fiche_ollama;
  const box = h("div", { class: "banner", style: "opacity:.92" });
  if (!S.ollama.ok) {
    box.append("Ollama n'est pas détecté (brouillon local facultatif). Les champs tirés de tes données sont déjà pré-remplis.");
    return box;
  }
  const run = async () => {
    try {
      const r = await api("POST", `/api/projects/${S.project}/fiche/ollama`, {});
      S.job = r.job; renderMain();
      const j = await waitJob(r.job);
      S.job = null;
      if (j.status !== "terminé") { toast("Échec : " + (j.error || ""), true); renderMain(); return; }
      const { filled, kept } = fillFiche(step, j.result.fields, j.result.model, false);
      await openProject(S.project, true);
      toast(`${filled.length} champ(s) rempli(s) par ${j.result.model}` + (kept.length ? `, ${kept.length} déjà rempli(s) gardé(s)` : "") + " : vérifie-les avant de générer");
    } catch (e) { S.job = null; toast(e.message, true); renderMain(); }
  };
  box.append(h("b", {}, `Brouillon des textes par ${S.ollama.model} (Ollama)`),
    " : nom usuel, taille, catalogues, découverte, origine du nom, nature, anecdote. Il ne remplit que les champs vides et laisse vide ce dont il n'est pas sûr. " +
    "Brouillon seulement : testés sur NGC 6960, NGC 7000 et M33, les modèles locaux (qwen2.5:7b, bonsai-2:27b) se trompaient sur la plupart des faits (nature de l'objet, distance, découvreur, catalogues). Préfère les textes vérifiés ci-dessus.",
    h("div", { class: "actions", style: "margin:8px 0 0" },
      h("button", { disabled: !!S.job, onclick: run }, "Brouillon des textes (Ollama)"),
      prev ? h("button", { class: "ghost", onclick: () => { const r = fillFiche(step, prev.fields, prev.model, false); toast(`${r.filled.length} champ(s) repris du brouillon du ${prev.date}`); renderMain(); } }, `Reprendre le brouillon du ${prev.date}`) : null,
      S.ficheKept ? h("button", { class: "ghost", onclick: () => { const k = S.ficheKept; fillFiche(step, k.fields, k.model, true); S.ficheKept = null; toast("Champs déjà remplis remplacés par le brouillon"); renderMain(); } },
        "Remplacer aussi les champs déjà remplis") : null));
  if (S.ficheKept) box.append(h("div", { class: "muted small", style: "margin-top:6px" }, "Gardés tels quels : " + Object.keys(S.ficheKept.fields).filter(k => S.ficheKept.fields[k] && initEditor(step)[0][k] !== S.ficheKept.fields[k]).map(k => lab[k] || k).join(", ")));
  return box;
}
