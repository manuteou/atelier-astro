// Suivi des travaux en arrière-plan : journal, barre de progression, bouton « Annuler ».
// Un seul suivi à la fois (le serveur n'exécute qu'un travail à la fois) : watchJob est la seule boucle de suivi ;
// pollJob (lancement d'une étape) et waitJob (attendre un résultat) s'appuient dessus.
import { $, h, S, api, toast, toggleConsole } from "./core.js";
import { renderMain } from "./page.js";
import { openProject } from "./projet.js";

const FIN = ["terminé", "échec", "annulé"];

const LOG_MAX = 3000;                         // lignes gardées à l'écran (le journal complet reste sur le serveur)
function appendLog(lines) {
  const pre = $("#log");
  pre.append(document.createTextNode(lines.join("\n") + "\n"));
  while (pre.childNodes.length > 60) pre.removeChild(pre.firstChild);    // ~60 paquets de lignes
  const n = (pre.textContent.match(/\n/g) || []).length;
  if (n > LOG_MAX) pre.textContent = pre.textContent.split("\n").slice(-LOG_MAX).join("\n");
  pre.scrollTop = pre.scrollHeight;
}

function renderJob(j) {
  const running = j.status === "en cours" || j.status === "en attente";
  $("#jobTitle").innerHTML = "";
  $("#jobTitle").append(running ? h("span", { class: "spin" }) : "", " ", j.title, h("span", { class: "muted" }, `  ${j.duree} s`));
  const js = $("#jobStatus");
  js.textContent = j.status;
  js.className = "pill small " + (j.status === "terminé" ? "ok" : j.status === "échec" ? "bad" : j.status === "annulé" ? "warn" : "");
  const pr = j.progress || {};
  const pct = running ? (pr.pct ?? 0) : (j.status === "terminé" ? 100 : 0);
  $("#jobProgress").classList.toggle("hidden", !running && j.status !== "terminé");
  $("#jobBar").style.width = pct + "%";
  const silence = running && pr.silence >= 120 ? ` · Siril silencieux depuis ${Math.floor(pr.silence / 60)} min${pr.silence >= 600 ? " (bloqué ? Annuler puis relancer)" : " (calcul long, ou blocage)"}` : "";
  $("#jobDetail").textContent = j.status === "en attente" && j.attente
    ? `en attente : ${j.attente} traitement(s) avant celui-ci (le PC n'en fait qu'un à la fois)`
    : running
    ? ([pr.partie, pr.detail && pr.sous_pct != null ? `${pr.detail} ${Math.round(pr.sous_pct)} %` : pr.detail].filter(Boolean).join(" · ") || "démarrage…") + silence
    : "";
  const c = $("#jobCancel");
  c.classList.toggle("hidden", !running);
  c.disabled = !j.cancellable;
}

export function cancelJob() {
  if (!S.watch) return;
  $("#jobCancel").disabled = true;
  api("POST", `/api/jobs/${S.watch}/cancel`).catch(e => toast(e.message, true));
}

/** Suit un travail jusqu'à la fin ; résout avec son état final. */
export function watchJob(id, { openConsole = false } = {}) {
  S.watch = id;
  if (openConsole) toggleConsole(true);
  $("#log").textContent = "";
  let since = 0;
  return new Promise((resolve) => {
    let fails = 0;
    const tick = async () => {
      let j;
      try { j = await api("GET", `/api/jobs/${id}?since=${since}`, null, 10000); fails = 0; }
      catch (e) {
        fails++;                                    // jamais de suivi figé sans le dire
        if (fails >= 2) $("#jobDetail").textContent = `⚠ ${e.message} — nouvel essai…`;
        setTimeout(tick, 2000); return;
      }
      since = j.log_len;
      if (j.log.length) appendLog(j.log);
      renderJob(j);
      if (FIN.includes(j.status)) {
        if (S.watch === id) S.watch = null;
        if (j.status === "échec") { toast("Échec : " + (j.error || ""), true); toggleConsole(true); }
        if (j.status === "annulé") toast("Traitement annulé : rien n'a été modifié dans les étapes validées");
        resolve(j);
        return;
      }
      setTimeout(tick, 600);
    };
    tick();
  });
}

/** Lancement d'une étape : suivi, puis rechargement du projet. */
export async function pollJob(id) {
  S.job = id; S.jobStep = S.sid;
  renderMain();
  const j = await watchJob(id);
  S.job = null;
  if (j.status === "terminé") delete S.edit[S.jobStep];
  await openProject(S.project, true);
}

/** Attendre le résultat d'un travail (import, avis, finalisation…). */
export function waitJob(id) {
  return watchJob(id, { openConsole: true });
}
