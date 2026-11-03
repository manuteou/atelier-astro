// Actions sur une étape : lancer, valider, passer, refaire la suite, appliquer un remède, rapport, avis Ollama.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "./core.js";
import { initEditor } from "./editeur.js";
import { renderMain } from "./page.js";
import { openProject, renderSteps } from "./projet.js";
import { pollJob, waitJob } from "./travaux.js";

// ------------------------------------------------------------------ actions
export async function runStep(step) {
  const variants = step.params.length ? (step.single ? S.edit[step.id].slice(0, 1) : S.edit[step.id]) : [{}];
  try {
    const r = await api("POST", `/api/projects/${S.project}/steps/${step.id}/run`, { variants });
    pollJob(r.job);
  } catch (e) { toast(e.message, true); }
}

export async function validate(step, i) {
  try {
    await api("POST", `/api/projects/${S.project}/steps/${step.id}/validate`, { variant: i });
    toast(`${step.id} : variante ${LETTERS[i]} validée`);
    await avancer(step);
  } catch (e) { toast(e.message, true); }
}

/** Passe à l'étape suivante. Une étape automatique sans réglage (image naturelle P7T, fusion P9) est lancée et validée
 *  d'elle-même ; on ne s'y arrête que si elle échoue ou affiche une alerte. */
async function avancer(step) {
  const idx = S.data.steps.findIndex(s => s.id === step.id);
  await openProject(S.project, true);
  const next = S.data.steps.slice(idx + 1).find(s => s.applies);
  if (!next) return;
  S.sid = next.id; renderSteps(); renderMain();
  if (next.kind !== "auto" || next.params.length || !next.ready || S.job) return;
  try {
    const r = await api("POST", `/api/projects/${S.project}/steps/${next.id}/run`, { variants: [{}] });
    await pollJob(r.job);
    const st = stepById(next.id)?.state;
    const v = st?.variants?.[0];
    if (!v || v.error || (v.info || []).some(l => String(l).startsWith("ATTENTION"))) {
      if (v && !v.error) toast(`${next.id} fait automatiquement, mais avec une alerte : regarde avant de valider`, true);
      S.sid = next.id; renderSteps(); renderMain();
      return;
    }
    await api("POST", `/api/projects/${S.project}/steps/${next.id}/validate`, { variant: 0 });
    toast(`${next.id} · ${next.title} : fait et validé automatiquement`);
    await avancer(next);
  } catch (e) { toast(e.message, true); }
}

export async function skipStep(step) {
  try {
    await api("POST", `/api/projects/${S.project}/steps/${step.id}/skip`);
    await avancer(step);
  } catch (e) { toast(e.message, true); }
}

export async function replay(until) {
  try {
    const r = await api("POST", `/api/projects/${S.project}/replay`, { until });
    S.job = r.job; renderMain();
    const j = await waitJob(r.job);
    S.job = null;
    if (j.status === "terminé") {
      const n = j.result.refaites;
      toast(`${n.length} étape(s) refaite(s)` + (n.some(x => x.alertes) ? " — il reste des alertes, regarde les résultats" : " — aucune alerte"));
      S.edit = {}; S.applied = null;
      const last = n.length ? n[n.length - 1].step : S.sid;
      S.returnTo = null;
      await openProject(S.project, true);
      S.sid = last; renderSteps(); renderMain();
    } else await openProject(S.project, true);
  } catch (e) { S.job = null; toast(e.message, true); }
}

export function applyRemedy(r, tgtId) {
  const from = S.sid;
  const step = stepById(tgtId);
  if (!step) return;
  const list = initEditor(step);
  const done = [];
  for (const [k, v] of Object.entries(r.reglages || {})) {
    const p = step.params.find(q => q.name === k);
    if (!p) continue;                                     // réglage d'une autre méthode : ignoré
    list.forEach((vals, i) => {
      const before = vals[k];
      let nv = v;
      if (typeof v === "string" && /^[+-]\d/.test(v) && typeof before === "number") {
        nv = before + parseFloat(v);
        if (p.min != null) nv = Math.max(p.min, nv);
        if (p.max != null) nv = Math.min(p.max, nv);
        const dec = String(p.step ?? 0.01).split(".")[1]?.length || 0;
        nv = parseFloat(nv.toFixed(dec));
      }
      if (JSON.stringify(before) !== JSON.stringify(nv)) {
        vals[k] = nv;
        const show = (x) => Array.isArray(x) ? x.join(" ") : (x === true ? "oui" : x === false ? "non" : x);
        done.push(`${list.length > 1 ? LETTERS[i] + " · " : ""}${p.label} : ${show(before)} → ${show(nv)}`);
      }
    });
  }
  S.applied = { step: tgtId, from, lines: done };
  S.returnTo = from;
  S.sid = tgtId; renderSteps(); renderMain();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

export async function copyReport(step) {
  try {
    const r = await api("GET", `/api/projects/${S.project}/steps/${step.id}/report`);
    try { await navigator.clipboard.writeText(r.text); toast("Rapport copié : colle-le dans la conversation avec Claude"); }
    catch (e) { openDlg("Rapport de l'étape (à copier)", h("textarea", { style: "min-height:60vh;font-family:var(--mono);font-size:12px" }, r.text)); }
  } catch (e) { toast(e.message, true); }
}

export async function askOllama(step) {
  try {
    const r = await api("POST", `/api/projects/${S.project}/steps/${step.id}/advice`, {});
    S.job = r.job; renderMain();
    const j = await waitJob(r.job);
    S.job = null;
    if (j.status === "terminé") S.advice[step.id] = { text: j.result.advice, model: j.result.model };
    await openProject(S.project, true);
    $("#adviceBox")?.scrollIntoView({ behavior: "smooth", block: "center" });
  } catch (e) { S.job = null; toast(e.message, true); }
}
