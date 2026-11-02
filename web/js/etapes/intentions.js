// « Dis ce que tu veux » : phrases toutes faites par étape (changement de réglages fixe, sans modèle) et phrase
// libre traduite en réglages par Ollama (contrôlés côté serveur). Rien n'est lancé : les réglages changent, on regarde,
// on lance.
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
  // seulement pour les choix de rendu : une étape qui mesure (S4) ou purement technique n'a rien à « régler au goût »
  if (!step.phrases?.length && (!S.ollama.ok || step.kind !== "creatif")) return null;
  const msg = h("div", { class: "hint intent-msg" });
  const show = (title, lines, extra) => {
    S.intentMsg = { step: step.id, title, lines, extra };
    renderMain();
  };
  const chip = (ph) => h("button", { class: "chip", title: Object.entries(ph.reglages).map(([k, v]) => `${k} ${v}`).join(", "),
    onclick: () => { const l = applyChanges(step, ph.reglages); show(`« ${ph.texte} »`, l); } }, ph.texte);
  const input = h("input", { type: "text", placeholder: S.ollama.ok ? "ou dis-le avec tes mots, ex. « le ciel un peu plus noir sans perdre les volutes »" : "Ollama non détecté : phrases toutes faites seulement", disabled: !S.ollama.ok });
  const go = h("button", { class: "small", disabled: !S.ollama.ok, onclick: async () => {
    const text = input.value.trim();
    if (!text) return;
    go.disabled = true; go.textContent = "…";
    try {
      const r = await api("POST", `/api/projects/${S.project}/steps/${step.id}/intention`, { text, vals: initEditor(step)[0] });
      const l = applyChanges(step, r.reglages);
      show(`« ${text} » (${r.modele})`, l, (r.explication || "") + (r.refuses?.length ? ` — ignoré : ${r.refuses.join(", ")}` : ""));
    } catch (e) { toast(e.message, true); go.disabled = false; go.textContent = "Appliquer"; }
  } }, "Appliquer");
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") go.click(); });
  const m = S.intentMsg?.step === step.id ? S.intentMsg : null;
  if (m) {
    msg.append(h("b", {}, m.title + " : "), m.lines.length ? m.lines.join(" · ") : "aucun réglage à changer pour la méthode choisie",
      m.extra ? h("div", { class: "muted" }, m.extra) : null,
      m.lines.length ? h("div", { class: "muted" }, "Rien n'est lancé : regarde les réglages, puis « Lancer ».") : null);
  }
  return h("div", { class: "intent" }, h("div", { class: "intent-row" }, h("span", { class: "intent-lab" }, "Dis ce que tu veux :"),
    (step.phrases || []).map(chip)), h("div", { class: "intent-row" }, input, go), m ? msg : null);
}
