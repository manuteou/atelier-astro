// Réglages d'une étape : variantes, champs (curseurs, choix, couleurs, cadres…).
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "./core.js";
import { ficheMark } from "./etapes/fiche.js";

// ------------------------------------------------------------------ éditeur de variantes
export function defaultsOf(step) {
  const d = {};
  for (const p of step.params) d[p.name] = p.default;
  return Object.assign(d, step.dyn || {});
}

export function initEditor(step) {
  if (S.edit[step.id]) return S.edit[step.id];
  const base = defaultsOf(step);
  let list;
  const pre = S.data.state.preset?.steps?.[step.id];
  if (step.state.variants?.length && step.state.variants[0].params) list = step.state.variants.map(v => ({ ...base, ...v.params }));
  else if (Array.isArray(pre)) list = pre.map(v => ({ ...base, ...v }));
  else list = (step.default_variants?.length ? step.default_variants : [{}]).map(v => ({ ...base, ...v }));
  S.edit[step.id] = list;
  return list;
}

export function visible(p, vals) {
  if (!p.show_if) return true;
  return Object.entries(p.show_if).every(([k, allowed]) => allowed.includes(vals[k]));
}

export function fieldFor(step, vals, p, onChange) {
  const set = (v) => { vals[p.name] = v; onChange(p.name); };
  const mk = step.id === "P13" ? ficheMark(step, vals, p.name) : null;
  const hint = mk ? h("div", { class: "hint mark-" + (mk === "données" ? "auto" : "ollama") },
    mk === "données" ? "Rempli d'après tes données : vérifie et modifie si besoin." :
    mk === "Claude" ? "Rempli par Claude (faits cherchés et sourcés) : relis-le." : `Brouillon de ${mk} (modèle local) : à vérifier, souvent faux (dates, noms, distances).`)
    : p.help ? h("div", { class: "hint" }, p.help) : null;
  if (p.type === "bool")
    return h("div", { class: "field check" }, h("label", {}, h("input", { type: "checkbox", checked: !!vals[p.name], onchange: e => set(e.target.checked) }), p.label), hint);
  if (p.type === "choice") {
    const sel = h("select", { onchange: e => set(e.target.value) }, p.choices.map(([v, l]) => h("option", { value: v, selected: String(vals[p.name]) === String(v) }, l)));
    return h("div", { class: "field" }, h("label", {}, p.label), sel, hint);
  }
  if (p.type === "float" || p.type === "int") {
    const num = h("input", { type: "number", step: p.step ?? "any", min: p.min, max: p.max, value: vals[p.name] ?? "" });
    const rng = h("input", { type: "range", step: p.step ?? "any", min: p.min, max: p.max, value: vals[p.name] ?? p.min });
    const upd = (v) => { const x = p.type === "int" ? parseInt(v) : parseFloat(v); if (!isNaN(x)) { vals[p.name] = x; num.value = x; rng.value = x; } };
    rng.oninput = e => upd(e.target.value);
    num.onchange = e => upd(e.target.value);
    return h("div", { class: "field" }, h("label", {}, p.label), h("div", { class: "row" }, rng, num), hint);
  }
  if (p.type === "rect") {
    const v = vals[p.name] || [0, 0, 0, 0];
    const ins = ["x", "y", "l", "h"].map((n, i) => h("input", { type: "number", value: v[i] ?? 0, title: n, style: "width:62px", onchange: () => set(ins.map(x => parseInt(x.value) || 0)) }));
    return h("div", { class: "field" }, h("label", {}, p.label), h("div", { class: "row" }, ins), h("div", { class: "hint" }, "Ou dessine-le à la souris sur l'image ci-dessus."));
  }
  if (p.type === "color")
    return h("div", { class: "field" }, h("label", {}, p.label),
      h("div", { class: "row" }, h("input", { type: "color", value: vals[p.name] || p.default, oninput: e => { vals[p.name] = e.target.value; e.target.nextSibling.textContent = e.target.value; } }),
        h("span", { class: "mono muted" }, vals[p.name] || p.default)), hint);
  if (p.type === "textarea")
    return h("div", { class: "field" }, h("label", {}, p.label), h("textarea", { oninput: e => { vals[p.name] = e.target.value; } }, vals[p.name] ?? ""), hint);
  return h("div", { class: "field" }, h("label", {}, p.label), h("input", { type: "text", value: vals[p.name] ?? "", oninput: e => { vals[p.name] = e.target.value; } }), hint);
}

export function renderEditor(step, box) {
  const list = initEditor(step);
  box.innerHTML = "";
  if (!step.params.length) return;
  const multi = !step.single;
  list.forEach((vals, i) => {
    const card = h("div", { class: "vcard" + (step.kind === "formulaire" ? " wide" : "") });
    if (step.kind === "formulaire") card.style.maxWidth = "760px", card.style.minWidth = "min(760px, 100%)";
    const head = h("h3", {}, multi ? h("span", { class: "tag" }, LETTERS[i]) : null, multi ? "Variante" : "Réglages", h("span", { class: "spacer" }),
      multi && list.length < 6 ? h("button", { class: "ghost small", title: "Dupliquer", onclick: () => { list.splice(i + 1, 0, { ...vals }); renderEditor(step, box); } }, "⧉") : null,
      multi && list.length > 1 ? h("button", { class: "ghost small", title: "Retirer", onclick: () => { list.splice(i, 1); renderEditor(step, box); } }, "✕") : null);
    card.append(head);
    const fields = h("div");
    const draw = () => {
      fields.innerHTML = "";
      for (const p of step.params) if (visible(p, vals)) fields.append(fieldFor(step, vals, p, (name) => { if (step.params.some(q => q.show_if && name in q.show_if)) draw(); }));
    };
    draw();
    card.append(fields);
    box.append(card);
  });
}

export function paramSummary(step, prm) {
  return step.params.filter(p => visible(p, prm) && !["textarea"].includes(p.type) && prm[p.name] !== "" && prm[p.name] != null && prm[p.name] !== false)
    .map(p => `${p.name}=${Array.isArray(prm[p.name]) ? prm[p.name].join(",") : prm[p.name]}`).join(" · ");
}
