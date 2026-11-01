// Fenêtre « Finaliser le travail » : dossier final puis nettoyage.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";
import { dlgNewProject } from "../fenetres/nouveau_projet.js";
import { loadProjects, openProject } from "../projet.js";
import { waitJob } from "../travaux.js";

export async function dlgFinalize() {
  let pl;
  try { pl = await api("GET", `/api/projects/${encodeURIComponent(S.project)}/finalize`); } catch (e) { toast(e.message, true); return; }
  const body = h("div", {});
  const nom = h("input", { type: "text", value: pl.nom });
  const where = h("div", { class: "hint mono" }, pl.dest);
  const keep = h("ul", { class: "fin-list" });
  const del = h("ul", { class: "fin-list" });
  const warn = h("div", {});
  const totals = h("div", { class: "muted" });
  const draw = (x) => {
    pl = x;
    where.textContent = x.dest;
    keep.innerHTML = ""; del.innerHTML = ""; warn.innerHTML = "";
    x.garde.forEach(k => keep.append(h("li", {}, h("b", {}, k.label), " — ", h("span", { class: "mono" }, k.name), h("span", { class: "muted" }, "  " + fmtSize(k.size)))));
    x.supprime.forEach(d => del.append(h("li", {}, h("b", {}, d.label), h("span", { class: "muted" }, "  " + fmtSize(d.size)), h("div", { class: "hint mono" }, d.path))));
    x.avertissements.forEach(w => warn.append(h("div", { class: "banner warn" }, w)));
    totals.textContent = `Gardé : ${fmtSize(x.taille_gardee)} · libéré : ${fmtSize(x.taille_liberee)}`;
  };
  let t = null;
  nom.oninput = () => { clearTimeout(t); t = setTimeout(async () => { try { draw(await api("GET", `/api/projects/${encodeURIComponent(S.project)}/finalize?nom=${encodeURIComponent(nom.value)}`)); } catch (e) { toast(e.message, true); } }, 350); };
  draw(pl);
  const sure = h("input", { type: "checkbox" });
  const go = h("button", { class: "danger", disabled: true, onclick: async () => {
    try {
      const r = await api("POST", `/api/projects/${encodeURIComponent(S.project)}/finalize`, { nom: nom.value, confirme: true });
      closeDlg(); S.job = r.job;
      const j = await waitJob(r.job);
      S.job = null;
      if (j.status === "terminé") {
        toast(`Travail finalisé : ${j.result.fichiers.length} fichier(s) dans « ${j.result.dest.split(/[\\/]/).pop()} », ${fmtSize(j.result.libere)} libérés`);
        localStorage.removeItem("atelier.project"); S.project = null; S.data = null; S.edit = {};
        await loadProjects(null);
        $("#steps").innerHTML = "";
        $("#main").innerHTML = "";
        $("#main").append(h("div", { class: "banner info" }, h("b", {}, "Travail finalisé. "), `Tes fichiers sont dans : ${j.result.dest}`,
          h("div", { class: "actions", style: "margin:8px 0 0" }, h("button", { onclick: () => dlgNewProject() }, "Nouveau projet"))));
      } else { await openProject(S.project, true); }
    } catch (e) { S.job = null; toast(e.message, true); }
  } }, "Finaliser et supprimer le dossier de travail");
  sure.onchange = () => { go.disabled = !sure.checked; };
  body.append(
    h("div", { class: "field" }, h("label", {}, "Nom du dossier final (nom de l'observation - lieu - date)"), nom, where),
    warn,
    h("h3", {}, "Gardé dans ce dossier"), keep,
    h("h3", {}, "Supprimé"), del,
    h("p", { class: "muted" }, "Les poses d'origine (lights, darks, flats, offsets) ne sont pas touchées : tu pourras toujours tout refaire depuis elles. Mais les essais, les variantes et les réglages du projet disparaissent (NOTES.md, copié dans le dossier final, garde la trace des réglages retenus)."),
    totals,
    h("div", { class: "field check", style: "margin-top:10px" }, h("label", {}, sure, "J'ai vérifié les images finales : supprimer le dossier de travail (irréversible)")),
    h("div", { class: "actions" }, go, h("button", { class: "ghost", onclick: closeDlg }, "Annuler")));
  openDlg("Finaliser le travail", body);
}
