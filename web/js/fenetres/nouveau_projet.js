// Fenêtre « Nouveau projet » : import d'un dossier en vrac ou sessions déjà rangées.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";
import { loadProjects } from "../projet.js";
import { waitJob } from "../travaux.js";

export async function dlgNewProject(tab = "import") {
  const target = h("input", { type: "text", placeholder: "ex. NGC 7000" });
  const type = h("select", {}, h("option", { value: "nebuleuse" }, "Nébuleuse"), h("option", { value: "galaxie" }, "Galaxie"));
  const device = { value: "" };              // le matériel est lu dans les en-têtes des poses (fiche « Matériel »)
  const common = h("div", {},
    h("div", { class: "row", style: "display:flex;gap:12px" }, h("div", { class: "field", style: "flex:2" }, h("label", {}, "Cible"), target),
      h("div", { class: "field", style: "flex:1" }, h("label", {}, "Type"), type)));
  const onglets = [["import", "Importer un dossier (tri automatique)"], ["sessions", "Sessions déjà rangées"],
    ["stack", "Partir d'une image empilée"]];
  const tabs = h("div", { class: "seg", style: "margin-bottom:14px;display:inline-flex;flex-wrap:wrap" },
    onglets.map(([k, l]) => h("button", { class: tab === k ? "on" : "", onclick: () => dlgNewProject(k) }, l)));
  const body = h("div", {}, tabs);

  if (tab === "import") {
    const path = h("input", { type: "text", placeholder: "ex. D:\\Seestar\\MyWorks ou E:\\ (copie le chemin depuis l'Explorateur)", value: localStorage.getItem("atelier.import") || "" });
    const mode = h("select", {},
      h("option", { value: "lien" }, "Liens (recommandé : aucune place en plus, originaux intacts ; copie si autre disque)"),
      h("option", { value: "copie" }, "Copier (originaux intacts, prend de la place)"),
      h("option", { value: "deplacer" }, "Déplacer (vide le dossier d'origine)"));
    const res = h("div", {});
    const analyse = h("button", {
      onclick: async () => {
        res.innerHTML = ""; res.append(h("div", { class: "muted" }, h("span", { class: "spin" }), " Lecture des en-têtes…"));
        localStorage.setItem("atelier.import", path.value.trim());
        let scan;
        try { scan = await api("POST", "/api/import/scan", { path: path.value }); } catch (e) { res.innerHTML = ""; toast(e.message, true); return; }
        afficherAnalyse(res, scan, target, type, mode);
      }
    }, "Analyser");
    body.append(h("p", { class: "muted" }, "Indique n'importe quel dossier (même en vrac, avec sous-dossiers, plusieurs appareils, filtres et nuits mélangés). L'appli lit l'en-tête de chaque pose (tout appareil à caméra couleur) et range tout en sessions : une cible + un appareil + un filtre + une nuit. Les darks, flats et offsets trouvés sont rangés avec les poses qui leur correspondent (même appareil, même taille, même durée pour les darks, même filtre pour les flats) et serviront à la calibration ; les empilements sont ignorés."),
      h("div", { class: "field" }, h("label", {}, "Dossier à importer"), h("div", { class: "row", style: "display:flex;gap:8px" }, path, analyse)),
      common, res);
  } else if (tab === "stack") {
    const path = h("input", { type: "text", placeholder: "ex. D:\\Astrophoto\\C 15\\Stacked_22_C 15_60.0s_IRCUT.fit (copie le chemin depuis l'Explorateur)",
      value: localStorage.getItem("atelier.stack") || "" });
    const res = h("div", {});
    const go = h("button", { onclick: async () => {
      res.innerHTML = "";
      localStorage.setItem("atelier.stack", path.value.trim());
      let a;
      try { a = await api("POST", "/api/stack/analyse", { path: path.value }); } catch (e) { toast(e.message, true); return; }
      if (!target.value && a.object) target.value = a.object;
      const hm = (s) => s ? `${Math.floor(s / 3600)} h ${String(Math.round((s % 3600) / 60)).padStart(2, "0")}` : "?";
      res.append(h("div", { class: "banner info", style: "margin:10px 0" },
        h("b", {}, a.name), ` · ${a.taille[0]}×${a.taille[1]} px · ${a.canaux === 3 ? "couleur" : "monochrome"}`,
        a.poses ? ` · ${a.poses} poses${a.exptime ? " de " + a.exptime + " s" : ""} (${hm(a.integration_s)})` : " · nombre de poses inconnu",
        ` · filtre ${a.filter_name || a.filter || "?"} · ${a.instrument || "appareil inconnu"}${a.focal ? " (" + a.focal + " mm)" : ""}`,
        a.date ? ` · ${a.date.slice(0, 10)}` : "", a.bias ? ` · piédestal ${a.bias} (retiré à l'import)` : "",
        a.plate_solve ? " · astrométrie présente" : ""),
        h("div", { class: "muted small" }, "L'image est copiée dans le projet (l'original n'est pas touché). L'inventaire, l'alignement et l'empilement sont sautés : le traitement reprend à la mesure du stack (S4, facultative) puis au cadrage (P0)."),
        h("div", { class: "actions" }, h("button", { onclick: async () => {
          try {
            const r = await api("POST", "/api/projects/depuis_stack", { path: path.value, target: target.value, type: type.value });
            closeDlg(); S.edit = {}; await loadProjects(r.name);
            toast("Projet créé à partir de l'image empilée" + (r.remarques.length ? " : " + r.remarques.join(", ") : ""));
          } catch (e) { toast(e.message, true); }
        } }, "Créer le projet")));
    } }, "Analyser");
    body.append(h("p", { class: "muted" }, "Pour repartir directement sur le traitement sans réempiler : un stack du Seestar (Stacked_…fit), d'un autre logiciel (Siril, DSS…) ou d'un ancien projet."),
      h("div", { class: "field" }, h("label", {}, "Image empilée (FITS)"), h("div", { class: "row", style: "display:flex;gap:8px" }, path, go)),
      common, res);
  } else {
    let ses = [];
    try { ses = await api("GET", "/api/sessions"); } catch (e) { toast(e.message, true); }
    const boxes = ses.map(s => ({ s, cb: h("input", { type: "checkbox" }) }));
    target.oninput = () => {
      const t = target.value.replace(/\s/g, "").toLowerCase();
      if (t.length > 2) boxes.forEach(b => { b.cb.checked = b.s.name.replace(/\s/g, "").toLowerCase().includes(t) || (b.s.object || "").replace(/\s/g, "").toLowerCase() === t; });
    };
    const list = h("div", { class: "seslist" }, boxes.length ? boxes.map(({ s, cb }) => h("label", {}, cb, h("b", {}, s.name),
      h("span", { class: "muted" }, ` ${s.count} poses · ${s.filter || "?"} · ${s.exptime || "?"} s · ${(s.date || "").slice(0, 10)} · ${s.device || s.instrument || ""}${s.focal ? " (" + s.focal + " mm)" : ""} ${s.object ? "· " + s.object : ""}`),
      s.mixed ? h("span", { style: "color:var(--warn)" }, " · " + s.mixed) : null))
      : h("div", { class: "muted", style: "padding:10px" }, `Aucune session trouvée dans ${S.cfg?.config.astro_root} (attendu : <SESSION>\\lights\\*.fit). Utilise « Importer un dossier ».`));
    body.append(common,
      h("div", { class: "field" }, h("label", {}, "Sessions (un dossier = un appareil + un filtre ; plusieurs appareils possibles)"), list),
      h("div", { class: "actions" }, h("button", {
        onclick: async () => {
          const sessions = boxes.filter(b => b.cb.checked).map(b => b.s.path);
          try {
            const r = await api("POST", "/api/projects", { target: target.value, type: type.value, device: device.value, sessions });
            closeDlg(); S.edit = {}; await loadProjects(r.name);
          } catch (e) { toast(e.message, true); }
        }
      }, "Créer le projet")));
  }
  openDlg("Nouveau projet", body);
}

/** Sessions trouvées dans le dossier importé : choix, rangement, création du projet. */
function afficherAnalyse(res, scan, target, type, mode) {
  res.innerHTML = "";
  const objs = {};
  scan.groups.forEach(g => objs[g.object] = (objs[g.object] || 0) + g.count);
  const main = Object.entries(objs).sort((a, b) => b[1] - a[1])[0]?.[0] || "";
  if (!target.value) target.value = main;
  const boxes = scan.groups.map(g => ({ g, cb: h("input", { type: "checkbox", checked: g.object === target.value }) }));
  const rej = Object.entries(scan.rejects).map(([k, v]) => `${v} ${k}`).join(" · ");
  res.append(h("div", { class: "muted", style: "margin:8px 0" }, `${scan.total} fichiers FITS lus, ${scan.groups.length} sessions trouvées` + (rej ? ` · écartés : ${rej}` : "")));
  res.append(h("div", { class: "table-scroll" }, h("table", { class: "flag", style: "width:100%" },
    h("tr", {}, h("th", {}, ""), h("th", {}, "Cible"), h("th", {}, "Appareil"), h("th", {}, "Filtre"), h("th", {}, "Nuit"), h("th", {}, "Poses"), h("th", {}, "Pose (s)"), h("th", {}, "Calibration"), h("th", {}, "")),
    boxes.map(({ g, cb }) => h("tr", {}, h("td", {}, cb), h("td", {}, g.object), h("td", {}, (g.instrument || g.device) + (g.focal ? ` (${g.focal} mm)` : "")),
      h("td", {}, (g.filter_name || "—") + (g.filter === "LP" ? " · bi-bande" : " · large bande")),
      h("td", {}, g.night), h("td", {}, g.count), h("td", {}, g.exptimes.join(", ")),
      h("td", { class: "muted" }, Object.entries(g.calib || {}).map(([k, v]) => `${v} ${k}`).join(", ") || "—"), h("td", { style: "color:var(--warn)" }, g.warnings.join(" ; ")))))));
  res.append(h("div", { class: "hint muted", style: "margin-top:6px" }, "Dossiers créés dans " + (S.cfg?.config.astro_root || "") + " : " + boxes.filter(b => b.cb.checked).map(b => b.g.folder).join(", ")));
  res.append(h("div", { class: "field", style: "margin-top:10px" }, h("label", {}, "Rangement"), mode));
  res.append(h("div", { class: "actions" }, h("button", {
    onclick: async () => {
      const ids = boxes.filter(b => b.cb.checked).map(b => b.g.id);
      try {
        const r = await api("POST", "/api/import/apply", { token: scan.token, ids, mode: mode.value, target: target.value, type: type.value, device: "" });
        closeDlg();
        const j = await waitJob(r.job);
        if (j.status === "terminé") { S.edit = {}; await loadProjects(j.result.name); toast("Poses rangées, projet prêt"); }
      } catch (e) { toast(e.message, true); }
    }
  }, "Ranger et créer le projet")));
}
