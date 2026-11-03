// Réglages par choix à cliquer : « réglages rapides » (changement fixe, sans modèle) et « meilleurs réglages par
// Ollama » pour un objectif choisi dans une liste (le modèle lit les mesures de l'étape ; résultat contrôlé côté serveur).
// Aucun texte libre : rien de ce qu'on tape ne part au modèle. Rien n'est lancé : les réglages changent, on regarde, on lance.
import { h, S, api, toast } from "../core.js";
import { initEditor, visible } from "../editeur.js";
import { renderMain } from "../page.js";

/** Applique des changements {réglage: valeur absolue ou « +0.1 »} à toutes les variantes ; renvoie les lignes changées. */
export function applyChanges(step, changes) {
  const list = initEditor(step);
  const lines = [];
  for (const [k, v] of Object.entries(changes || {})) {
    const p = step.params.find(q => q.name === k);
    if (!p) continue;
    list.forEach((vals, i) => {
      if (!visible(p, vals)) return;                      // réglage d'une autre méthode que celle choisie
      const before = vals[k];
      let nv = v;
      if (typeof v === "string" && /^[+-]\d/.test(v) && typeof before === "number") nv = before + parseFloat(v);
      if (typeof nv === "number") {
        if (p.min != null) nv = Math.max(p.min, nv);
        if (p.max != null) nv = Math.min(p.max, nv);
        const dec = String(p.step ?? 0.01).split(".")[1]?.length || 0;
        nv = p.type === "int" ? Math.round(nv) : parseFloat(nv.toFixed(Math.max(dec, 2)));
      }
      if (JSON.stringify(before) !== JSON.stringify(nv)) {
        vals[k] = nv;
        lines.push(`${list.length > 1 ? "variante " + "ABCDEF"[i] + " : " : ""}${p.label} ${before} → ${nv}`);
      }
    });
  }
  return lines;
}

export function intentBar(step) {
  const objs = S.ollama.ok ? (step.objectifs || []) : [];
  if (!step.phrases?.length && !objs.length) return null;
  const msg = h("div", { class: "hint intent-msg" });
  const show = (title, lines, extra) => {
    S.intentMsg = { step: step.id, title, lines, extra };
    renderMain();
  };
  const chip = (ph) => h("button", { class: "chip", title: Object.entries(ph.reglages).map(([k, v]) => `${k} ${v}`).join(", "),
    onclick: () => { const l = applyChanges(step, ph.reglages); show(`« ${ph.texte} »`, l); } }, ph.texte);
  const sansMesure = !(step.state?.variants || []).length;
  const objChip = (o) => {
    const b = h("button", { class: "chip ollama", title: "Ollama propose les meilleurs réglages pour cet objectif, d'après les mesures de la dernière série de variantes",
      disabled: !!S.job, onclick: async () => {
        b.disabled = true; const t0 = b.textContent; b.textContent = "… " + t0;
        try {
          const r = await api("POST", `/api/projects/${S.project}/steps/${step.id}/intention`, { objectif: o.cle, vals: initEditor(step)[0] });
          const l = applyChanges(step, r.reglages);
          show(`« ${r.objectif} » (${r.modele})`, l, (r.explication || "") + (r.refuses?.length ? ` — ignoré : ${r.refuses.join(", ")}` : ""));
        } catch (e) { toast(e.message, true); b.disabled = false; b.textContent = t0; }
      } }, o.texte);
    return b;
  };
  const m = S.intentMsg?.step === step.id ? S.intentMsg : null;
  if (m) {
    msg.append(h("b", {}, m.title + " : "), m.lines.length ? m.lines.join(" · ") : "aucun réglage à changer pour la méthode choisie",
      m.extra ? h("div", { class: "muted" }, m.extra) : null,
      m.lines.length ? h("div", { class: "muted" }, "Rien n'est lancé : regarde les réglages, puis « Lancer ».") : null);
  }
  return h("div", { class: "intent" },
    step.phrases?.length ? h("div", { class: "intent-row" }, h("span", { class: "intent-lab" }, "Réglages rapides :"), step.phrases.map(chip)) : null,
    objs.length ? h("div", { class: "intent-row" }, h("span", { class: "intent-lab" }, `Meilleurs réglages par ${S.ollama.model || "Ollama"} pour :`),
      objs.map(objChip),
      sansMesure && step.id !== "S3" ? h("span", { class: "muted small" }, " (lance d'abord une série de variantes : il s'appuiera sur leurs mesures)") : null) : null,
    m ? msg : null);
}
