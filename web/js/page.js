// Page d'une étape : aide, bandeaux, réglages, actions, cartes de résultats.
import { runStep, validate, skipStep, replay, applyRemedy, copyReport, askOllama } from "./actions.js";
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "./core.js";
import { comparables, dlgCompare, syncImage } from "./comparer.js";
import { initEditor, renderEditor, paramSummary } from "./editeur.js";
import { cropper } from "./etapes/cadrage.js";
import { posePicker } from "./etapes/poses.js";
import { amasPicker } from "./etapes/amas.js";
import { zonesPicker } from "./etapes/zones.js";
import { intentBar } from "./etapes/intentions.js";
import { ficheTools } from "./etapes/fiche.js";
import { liveTuner } from "./etapes/reglage_fin.js";
import { retoucher } from "./etapes/retouches.js";
import { dlgFinalize } from "./fenetres/finaliser.js";
import { openViewer } from "./visionneuse.js";

// ------------------------------------------------------------------ page d'étape
export function renderMain() {
  const step = stepById(S.sid);
  const main = $("#main");
  main.innerHTML = "";
  const st = step.state || {};
  const status = st.status || "todo";
  main.append(h("div", { class: "head" }, h("h1", {}, `${step.id} · ${step.title}`),
    h("span", { class: "kind " + step.kind }, { technique: "technique", creatif: "choix de rendu", auto: "automatique", formulaire: "formulaire" }[step.kind]),
    h("span", { class: "status-line muted" }, STATUS[status] || status)));
  main.append(h("p", { class: "help" }, step.help));
  if (step.summary?.length) {                 // les adresses web deviennent des liens (carte de pollution lumineuse…)
    const sum = h("div", { class: "banner info summary" });
    step.summary.join("\n").split(/(https?:\/\/\S+)/).forEach((part, i) =>
      sum.append(i % 2 ? h("a", { href: part, target: "_blank", rel: "noopener" }, i ? "carte ↗" : part) : part));
    main.append(sum);
  }

  const stale = S.data.steps.filter(s => s.state.status === "stale").map(s => s.id);
  if (stale.length && !S.job) {
    const until = S.returnTo && stale.includes(S.returnTo) ? S.returnTo : null;
    main.append(h("div", { class: "banner stale" },
      `${stale.length} étape(s) déjà validée(s) à refaire depuis ta dernière modification : ${stale.join(", ")}. ` +
      "L'appli peut les refaire d'elle-même avec les réglages que tu avais retenus, puis tu regardes le résultat.",
      h("div", { class: "actions", style: "margin:8px 0 0" },
        until ? h("button", { onclick: () => replay(until) }, `Refaire jusqu'à ${until} (d'où venait l'alerte)`) : null,
        h("button", { class: until ? "ghost" : "", onclick: () => replay(null) }, "Tout refaire"),
        h("span", { class: "muted" }, "ou relance-les une par une pour changer des réglages"))));
  }
  if (!step.applies) { main.append(h("div", { class: "banner info" }, "Étape sans objet : " + step.why)); return; }
  if (!step.ready) main.append(h("div", { class: "banner warn" }, "Pas encore possible : " + step.ready_msg));
  if (S.applied?.step === step.id) {
    const a = S.applied;
    main.append(h("div", { class: "banner info" }, a.lines.length
      ? `Réglages proposés par l'alerte de ${a.from} appliqués (rien n'est lancé) :\n` + a.lines.join("\n") + "\nVérifie-les, puis « Lancer »."
      : `Depuis l'alerte de ${a.from} : rien à changer dans les réglages, il suffit de relancer cette étape.`,
      h("div", { class: "actions", style: "margin:8px 0 0" }, h("button", { disabled: !!S.job, onclick: () => runStep(step) }, "Lancer avec ces réglages"),
        h("span", { class: "muted" }, `puis valide la variante qui te plaît : l'appli te proposera de refaire la suite jusqu'à ${a.from}.`))));
    main.lastChild.style.whiteSpace = "pre-line";
  }
  const pre = S.data.state.preset?.steps?.[step.id];
  if (pre === "passer") main.append(h("div", { class: "banner info" }, `Le preset « ${S.data.state.preset.name} » passait cette étape.`));
  else if (Array.isArray(pre) && !st.variants?.length) main.append(h("div", { class: "banner info" }, `Réglages pré-remplis par le preset « ${S.data.state.preset.name} » : rien n'est lancé sans toi.`));

  if (step.id === "P13" && step.ready) main.append(ficheTools(step));
  const box = h("div", { class: "variants" });
  const ib = step.ready && step.applies ? intentBar(step) : null;
  if (ib) main.append(ib);
  if (step.interaction === "crop") main.append(cropper(step, () => renderEditor(step, box)));
  if (step.interaction === "poses" && step.ready) main.append(posePicker(step, () => renderEditor(step, box)));
  if (step.id === "P7" && step.ready) { const a = amasPicker(step, () => renderEditor(step, box)); if (a) main.append(a); }
  if (step.id === "S4" && step.ready) { const z = zonesPicker(step, () => renderEditor(step, box)); if (z) main.append(z); }
  if (step.interaction === "live" && step.ready) main.append(liveTuner(step));
  if (step.interaction === "retouche" && step.ready) main.append(retoucher(step));
  main.append(box);
  if (step.interaction !== "live" && step.interaction !== "retouche") renderEditor(step, box);
  else initEditor(step);

  const list = S.edit[step.id];
  const actions = h("div", { class: "actions" });
  if (step.params.length && !step.single && list.length < 6)
    actions.append(h("button", { class: "ghost", onclick: () => { list.push({ ...list[list.length - 1] }); renderEditor(step, box); } }, "+ Variante"));
  const n = step.params.length && !step.single ? list.length : 1;
  const noRetouch = step.interaction === "retouche" && !(list[0]?.liste || "").trim();
  actions.append(h("button", { id: "btnRun", disabled: !step.ready || !!S.job || noRetouch, title: noRetouch ? "Clique d'abord sur un défaut dans l'image" : null, onclick: () => runStep(step) },
    step.kind === "formulaire" && step.id === "P13" ? "Générer la fiche" : step.interaction === "live" ? "Appliquer en pleine résolution" : step.interaction === "retouche" ? "Appliquer les retouches" : (n > 1 ? `Lancer les ${n} variantes` : "Lancer")));
  if (step.optional) actions.append(h("button", { class: "ghost", onclick: () => skipStep(step) }, "Passer l'étape"));
  if (step.params.length && step.kind !== "formulaire")
    actions.append(h("button", { class: "ghost", onclick: () => { delete S.edit[step.id]; S.data.steps.find(s => s.id === step.id).state.variants = []; renderMain(); } }, "Réglages par défaut"));
  if (comparables(step).length >= 2)
    actions.append(h("button", { class: "ghost", title: "Rideau avant/après entre la référence et les variantes, zoom identique des deux côtés", onclick: () => dlgCompare(step) }, "Comparer"));
  if (st.variants?.length) {
    actions.append(h("button", { class: "ghost", title: "Copie les réglages, mesures et alertes de cette étape : à coller dans la conversation avec Claude", onclick: () => copyReport(step) }, "Copier le rapport"));
    if (S.ollama.ok) actions.append(h("button", { class: "ghost", disabled: !!S.job, title: `Avis d'un modèle local (${S.ollama.model}) sur les chiffres de l'étape — il ne voit pas les images`, onclick: () => askOllama(step) }, "Avis local (Ollama)"));
  }
  if (S.data.state.zoom) actions.append(h("span", { class: "muted mono" }, "zoom : " + S.data.state.zoom.join(" ")));
  main.append(actions);
  const adv = S.advice[step.id] || st.advice;
  if (adv) {
    const box = h("div", { class: "banner info advice", id: "adviceBox" }, h("b", {}, `Avis indicatif de ${adv.model} (modèle local, ne voit pas les images)${adv.date ? " · " + adv.date : ""} :`), "\n" + adv.text);
    main.append(box);
  }
  renderResults(step, main);
  // tout en bas de la page : la finalisation vient après les réglages, la fiche et les résultats
  if ((step.id === "P12" || step.id === "P13") && S.data.state.facts?.exports)
    main.append(h("div", { class: "banner info finaliser" },
      h("b", {}, "Fin du traitement"), " : quand tout te convient, « Finaliser le travail » range la fiche PDF et les images finales dans un dossier à leur nom, puis supprime le dossier de travail. Rien ne se fait sans ta confirmation.",
      h("div", { class: "actions", style: "margin:8px 0 0" }, h("button", { disabled: !!S.job, onclick: () => dlgFinalize() }, "Finaliser le travail"))));
}

export function infoList(lines, remedes = {}) {
  if (!lines?.length) return null;
  const where = { ici: "à corriger ici : change les réglages et relance", suite: "une étape suivante s'en charge, tu peux continuer" };
  return h("ul", {}, lines.map(l => {
    const li = h("li", { class: /^ATTENTION|échec|ERREUR/i.test(l) ? "warn" : (/^OK|BILAN\s+aucun/.test(l) ? "okl" : "") }, l);
    const r = remedes[l];
    if (r) {
      const tgtId = r.etape === "ici" ? S.sid : (r.etape && !where[r.etape] ? r.etape : null);
      const n = Object.keys(r.reglages || {}).length;
      let label = null;
      if (tgtId && n) label = tgtId === S.sid ? "Appliquer les réglages proposés" : `Aller à ${tgtId} avec les réglages proposés`;
      else if (tgtId && tgtId !== S.sid) label = "Aller à " + tgtId;
      li.append(h("div", { class: "remedy" }, "→ " + r.conseil,
        r.etape ? h("span", { class: "muted" }, "  (" + (where[r.etape] || "revenir à " + r.etape) + ")") : null,
        label ? h("button", { class: "ghost small", onclick: () => applyRemedy(r, tgtId) }, label) : null));
    }
    return li;
  }));
}

export function resultCard(step, v, i, opts = {}) {
  const chosen = !opts.ref && step.state.chosen === i && ["done", "stale"].includes(step.state.status);
  const card = h("div", { class: "rcard" + (chosen ? " chosen" : "") + (opts.ref ? " ref" : "") + (v.error ? " err" : "") });
  card.append(h("div", { class: "rhead" }, h("span", { class: "tag" }, opts.ref ? "Réf." : LETTERS[i]),
    h("span", { class: "prm", title: opts.ref ? opts.refTitle : paramSummary(step, v.params || {}) }, opts.ref ? opts.refTitle : paramSummary(step, v.params || {})),
    (() => { const n = (v.info || []).filter(l => /^ATTENTION/.test(l)).length;
      if (v.error && !opts.ref) return h("span", { class: "alert on", title: "cette variante n'a pas abouti" }, "✕ échec");
      return opts.ref ? null : h("span", { class: "alert " + (n ? "on" : "ok"), title: n ? "contrôles automatiques : voir les lignes en orange" : "contrôles automatiques sans alerte" },
        n ? `⚠ ${n} alerte${n > 1 ? "s" : ""}` : "✓ contrôles"); })(),
    v.duree ? h("span", { class: "muted mono" }, v.duree + " s") : null));
  const pv = v.previews;
  if (pv?.main) {
    card.append(syncImage(step.id, fileUrl(pv.main), () => openViewer(step, pv, opts.ref ? "Référence" : `Variante ${LETTERS[i]}`)));
    if (pv.zoom) card.append(h("img", { class: "rimg rzoom", src: fileUrl(pv.zoom), title: "zoom (même zone pour toutes les variantes)", onclick: () => openViewer(step, { ...pv, main: pv.zoom, nointeract: true }, "Zoom") }));
  }
  const body = h("div", { class: "rbody" });
  if (v.error) body.append(h("div", { class: "banner warn" }, "Échec : " + v.error));
  if (v.stats) body.append(h("div", { class: "stats" }, `médianes ${v.stats.medianes.join("/")} · zéros ${v.stats.zeros_pct.join("/")} % · écrêtés ${v.stats.ecretes_pct} % · ${v.stats.taille.join("x")}`));
  if (!opts.ref && step.state.status === "stale")
    body.append(h("div", { class: "muted", style: "margin-bottom:4px" }, "Résultats d'avant ta dernière modification d'une étape précédente : refais cette étape pour des alertes à jour."));
  if (!opts.ref && v.info?.length) body.append(infoList(v.info, step.state.status === "stale" ? {} : (v.remedes || {})));
  if (step.id === "S2" && v.extra?.flagged) {
    const fl = v.extra.flagged;
    body.append(fl.length ? h("table", { class: "flag" }, h("tr", {}, h("th", {}, "index"), h("th", {}, "fichier"), h("th", {}, "fond"), h("th", {}, "étoiles"), h("th", {}, "raison")),
      fl.map(r => h("tr", {}, h("td", {}, r.index_seq_1), h("td", {}, r.fichier), h("td", {}, r.fond), h("td", {}, r.etoiles), h("td", {}, r.raison))))
      : h("div", { class: "muted" }, "Aucune pose signalée."));
    if (fl.length) body.append(h("div", { class: "hint muted" }, "Ces poses sont pré-remplies dans « Poses à écarter » à l'étape S3 ; retire celles que tu veux garder."));
  }
  card.append(body);
  if (v.images?.length && !opts.ref) card.append(h("div", { class: "thumbs" }, v.images.map(im => h("img", { src: fileUrl(im), onclick: () => openViewer(step, { main: im, nointeract: true }, im.split("/").pop()) }))));
  if (v.pdf && !opts.ref) card.append(h("div", { class: "rbody" }, h("a", { href: fileUrl(v.pdf), target: "_blank", style: "color:var(--accent2)" }, "Ouvrir le PDF ↗")));
  if (!opts.ref) {
    const foot = h("div", { class: "rfoot" });
    if (chosen) foot.append(h("span", { style: "color:var(--ok)" }, step.state.status === "stale" ? "✓ retenue (à revalider)" : "✓ retenue"));
    if (!v.error && (!chosen || step.state.status === "stale"))
      foot.append(h("button", { class: "ok", disabled: !!S.job, onclick: () => validate(step, i) }, `Valider ${LETTERS[i]}`));
    foot.append(h("span", { class: "spacer" }));
    if (v.params && step.params.length && !step.single)
      foot.append(h("button", { class: "ghost small", title: "Repartir de ces réglages pour une nouvelle variante", onclick: () => { const l = S.edit[step.id]; if (l.length < 6) { l.push({ ...v.params }); renderMain(); } } }, "Affiner"));
    card.append(foot);
  }
  return card;
}

export function renderResults(step, main) {
  const grid = h("div", { class: "results" });
  if (step.reference) {
    const r = stepById(step.reference);
    const rs = r?.state;
    if (rs?.retained?.previews) grid.append(resultCard(r, rs.retained, 0, { ref: true, refTitle: `${r.id} · ${r.title} (retenue)` }));
  }
  const st = step.state;
  if (st.retained?.previews && st.chosen == null && ["done", "stale"].includes(st.status))
    grid.append(resultCard(step, st.retained, 0, { ref: true, refTitle: `Retenue actuellement (essai ${st.retained.run}${st.retained.tag || ""}) : valider une nouvelle variante la remplacera` }));
  (step.state.variants || []).forEach((v, i) => grid.append(resultCard(step, v, i)));
  if (grid.children.length) {
    if (grid.querySelectorAll(".thumb-wrap").length > 1)
      main.append(h("div", { class: "hint", style: "margin:6px 0 4px" }, "Molette sur une image : même zoom sur toutes les variantes (glisser pour se déplacer, double-clic pour revenir). « Comparer » : rideau avant/après."));
    main.append(grid);
  }
}
