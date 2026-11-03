// Exploration des travaux terminés : une carte par cible, puis ses images finales, sa fiche PDF et ses notes.
// Lecture seule ; les dossiers viennent de « FINAUX TRAITES » (ou du dossier réglé dans Réglages).
import { $, h, api, toast, openDlg, closeDlg } from "./core.js";
import { waitJob } from "./travaux.js";

const enc = (rel) => rel.split("/").map(encodeURIComponent).join("/");
const vign = (rel, l = 480) => `/galerie/vignette/${enc(rel)}?l=${l}`;
const fich = (rel) => `/galerie/fichier/${enc(rel)}`;
const GENRE = { colorise: "colorisée", naturel: "naturelle", stack_brut: "stack brut", partage: "partage", autre: "" };
const TYPE = { nebuleuse: "nébuleuse", "nébuleuse": "nébuleuse", galaxie: "galaxie", amas: "amas" };

let data = null, filtre = "", lb = null;

export async function openExplorer() {
  let box = $("#explorer");
  if (!box) {
    box = h("section", { id: "explorer", class: "explorer" });
    document.body.append(box);
  }
  box.classList.remove("hidden");
  document.body.classList.add("explorer-open");
  box.innerHTML = "";
  box.append(h("div", { class: "muted", style: "padding:40px" }, "Lecture des travaux terminés…"));
  try {
    data = await api("GET", "/api/galerie");
  } catch (e) { toast(e.message, true); closeExplorer(); return; }
  grille();
}

export function closeExplorer() {
  $("#explorer")?.classList.add("hidden");
  document.body.classList.remove("explorer-open");
  fermerLb();
}

function barre(titre, retour) {
  return h("div", { class: "ex-bar" },
    retour ? h("button", { class: "ghost", onclick: retour }, "← Toutes les cibles") : null,
    h("h1", {}, titre),
    h("div", { class: "spacer" }),
    retour ? null : h("input", { type: "search", placeholder: "Chercher une cible, un lieu…", value: filtre,
      oninput: (e) => { filtre = e.target.value; remplir(); } }),
    retour ? null : h("button", { class: "ghost", title: "Fabriquer un site web de ces travaux et le publier (GitHub Pages)", onclick: dlgSite }, "Publier le site…"),
    h("button", { class: "ghost", onclick: closeExplorer }, "Fermer ✕"));
}

function grille() {
  const box = $("#explorer");
  box.innerHTML = "";
  const n = data.cibles.reduce((a, c) => a + c.travaux.length, 0);
  box.append(barre("Mes travaux"),
    h("div", { class: "muted small ex-sous" }, data.erreur ? data.erreur :
      `${data.cibles.length} cible(s), ${n} travail(aux) — dossier ${data.racine}`),
    h("div", { class: "ex-grille", id: "exGrille" }));
  remplir();
}

function remplir() {
  const g = $("#exGrille");
  if (!g) return;
  g.innerHTML = "";
  const f = filtre.trim().toLowerCase();
  const liste = data.cibles.filter(c => !f || [c.cible, c.type, ...c.travaux.map(t => `${t.lieu} ${t.date}`)]
    .join(" ").toLowerCase().includes(f));
  if (!liste.length) {
    g.append(h("div", { class: "muted" }, data.cibles.length ? "Aucune cible ne correspond." :
      "Aucun travail terminé trouvé ici. « Finaliser le travail » (P12 / P13) y range les images finales et la fiche."));
    return;
  }
  for (const c of liste) {
    const t0 = c.travaux[0];
    g.append(h("div", { class: "ex-carte", onclick: () => detail(c), title: "Voir les images et la fiche" },
      h("div", { class: "ex-img" }, c.couverture ? h("img", { src: vign(c.couverture), loading: "lazy", alt: c.cible }) :
        h("span", { class: "muted" }, "pas d'image")),
      h("div", { class: "ex-leg" },
        h("b", {}, c.cible),
        h("span", { class: "muted small" }, [TYPE[c.type] || c.type, t0.lieu, t0.date || t0.modifie].filter(Boolean).join(" · ")),
        h("span", { class: "small" },
          c.travaux.length > 1 ? `${c.travaux.length} traitements` : "",
          c.travaux.some(t => t.fiches.length) ? h("span", { class: "chip small" }, "fiche PDF") : null))));
  }
}

function detail(c) {
  const box = $("#explorer");
  box.innerHTML = "";
  box.append(barre(c.cible, grille));
  for (const t of c.travaux) {
    const f = t.faits || {};
    const infos = [t.lieu && `lieu : ${t.lieu}`, (t.date || t.modifie) && `nuit(s) : ${t.date || "—"}`,
      f.appareil, f.integration && `intégration ${f.integration}`, f.poses && `${f.poses} poses`, f.ciel && `ciel ${f.ciel}`]
      .filter(Boolean);
    const notesBox = h("pre", { class: "ex-notes hidden" });
    const pdfBox = h("div", { class: "ex-pdf hidden" });
    const sec = h("div", { class: "ex-travail" },
      h("div", { class: "ex-thead" },
        h("h2", {}, t.lieu || t.date ? [t.lieu, t.date].filter(Boolean).join(" — ") : t.id),
        h("span", { class: "muted small" }, `traité le ${t.modifie}`),
        h("div", { class: "spacer" }),
        ...t.fiches.map(p => h("button", { class: "small", onclick: () => basculerPdf(pdfBox, p) }, `Fiche PDF${t.fiches.length > 1 ? " · " + p.nom : ""}`)),
        t.notes ? h("button", { class: "ghost small", onclick: () => basculerNotes(notesBox, t.notes) }, "Notes") : null,
        h("button", { class: "ghost small", onclick: () => api("POST", "/api/galerie/ouvrir", { id: t.id }).catch(e => toast(e.message, true)) }, "Dossier")),
      infos.length ? h("div", { class: "muted small ex-infos" }, infos.join(" · ")) : null,
      h("div", { class: "ex-images" }, t.images.map((im, i) =>
        h("figure", { onclick: () => ouvrirLb(t.images, i, c.cible) },
          h("img", { src: vign(im.chemin, 360), loading: "lazy", alt: im.nom }),
          h("figcaption", { class: "small" }, [GENRE[im.genre], im.version > 1 ? `v${im.version}` : ""].filter(Boolean).join(" ") || im.nom)))),
      pdfBox, notesBox);
    box.append(sec);
  }
  box.scrollTop = 0;
}

function basculerPdf(el, p) {
  const on = el.classList.toggle("hidden");
  if (!on && !el.firstChild) {
    el.append(h("div", { class: "ex-pdf-bar" }, h("span", { class: "small muted" }, p.nom), h("div", { class: "spacer" }),
      h("a", { href: fich(p.chemin), target: "_blank", class: "small" }, "ouvrir dans un onglet ↗")),
      h("iframe", { src: fich(p.chemin), title: p.nom }));
  }
}

async function basculerNotes(el, rel) {
  const on = el.classList.toggle("hidden");
  if (!on && !el.textContent) {
    try { el.textContent = (await api("GET", `/api/galerie/notes/${enc(rel)}`)).texte; }
    catch (e) { el.textContent = e.message; }
  }
}

// ------------------------------------------------------------------ visionneuse plein écran
function ouvrirLb(images, i, titre) {
  fermerLb();
  const img = h("img", { alt: "" });
  const leg = h("span", { class: "small" });
  const voir = (k) => {
    i = (k + images.length) % images.length;
    const im = images[i];
    img.src = vign(im.chemin, 1600);            // rapide d'abord, pleine résolution ensuite
    const full = new Image();
    full.onload = () => { if (images[i] === im) img.src = full.src; };
    full.src = fich(im.chemin);
    leg.textContent = `${titre} — ${im.nom} (${i + 1}/${images.length})`;
  };
  lb = h("div", { class: "modal ex-lb", onclick: (e) => { if (e.target === lb || e.target === img.parentNode) fermerLb(); } },
    h("div", { class: "viewer-bar" }, leg, h("div", { class: "spacer" }),
      h("a", { class: "small", target: "_blank", onclick: (e) => { e.currentTarget.href = fich(images[i].chemin); } , href: "#" }, "pleine taille ↗"),
      h("button", { class: "ghost", onclick: () => voir(i - 1) }, "←"), h("button", { class: "ghost", onclick: () => voir(i + 1) }, "→"),
      h("button", { class: "ghost", onclick: fermerLb }, "Fermer ✕")),
    h("div", { class: "ex-lb-body" }, img));
  lb._key = (e) => { if (e.key === "ArrowLeft") voir(i - 1); else if (e.key === "ArrowRight") voir(i + 1); else if (e.key === "Escape") fermerLb(); };
  document.addEventListener("keydown", lb._key);
  document.body.append(lb);
  voir(i);
}

function fermerLb() {
  if (!lb) return;
  document.removeEventListener("keydown", lb._key);
  lb.remove();
  lb = null;
}

// ------------------------------------------------------------------ site web à publier
async function dlgSite() {
  let inf;
  try { inf = await api("GET", "/api/galerie/site"); } catch (e) { toast(e.message, true); return; }
  const titre = h("input", { type: "text", value: inf.titre || "Mes astrophotographies", style: "width:100%" });
  const depot = h("input", { type: "text", value: inf.depot, placeholder: "https://github.com/ton-compte/astro.git", style: "width:100%" });
  const etat = h("div", { class: "small muted", style: "margin-top:8px;white-space:pre-wrap" });
  const go = async (publier) => {
    if (publier && !depot.value.trim()) { toast("indique l'adresse du dépôt GitHub", true); return; }
    etat.textContent = publier ? "Fabrication puis envoi du site…" : "Fabrication du site…";
    try {
      const r = await api("POST", "/api/galerie/site", { titre: titre.value, depot: depot.value, publier });
      const j = await waitJob(r.job);
      if (j.status !== "terminé") { etat.textContent = "Échec : " + (j.error || "voir le journal"); return; }
      const x = j.result;
      etat.textContent = `${x.cibles} cible(s), ${x.travaux} travail(aux), ${x.taille_mo} Mo — dossier ${x.dossier}` +
        (x.publie === "envoyé" ? "\nEnvoyé : GitHub Pages met le site à jour en une minute environ." :
         x.publie === "inchangé" ? "\nRien de nouveau depuis la dernière publication." : "");
      if (!publier) api("POST", "/api/galerie/site/ouvrir").catch(() => {});
    } catch (e) { etat.textContent = "Échec : " + e.message; }
  };
  openDlg("Publier « Mes travaux » sur le web", h("div", {},
    h("p", { class: "small" }, "L'appli fabrique un site de fichiers (pages, images redimensionnées pour le web, fiches PDF ; jamais les FIT, TIFF ni NOTES). ",
      "Il se publie gratuitement sur GitHub Pages : ton PC peut rester éteint, personne n'a accès à l'appli."),
    h("label", { class: "small" }, "Titre du site"), titre,
    h("label", { class: "small", style: "display:block;margin-top:10px" }, "Dépôt GitHub qui recevra le site"), depot,
    h("details", { class: "small", style: "margin-top:8px" }, h("summary", {}, "Préparer le dépôt (une seule fois)"),
      h("ol", {},
        h("li", {}, "Sur github.com : « New repository », nom par exemple « astro », public, sans README."),
        h("li", {}, "Copie son adresse (https://github.com/ton-compte/astro.git) dans le champ ci-dessus."),
        h("li", {}, "Clique « Publier sur GitHub » ; la première fois, Git peut ouvrir la fenêtre de connexion à GitHub."),
        h("li", {}, "Sur le dépôt : Settings → Pages → Source « Deploy from a branch », branche « main », dossier « / (root) »."),
        h("li", {}, "Le site est à l'adresse https://ton-compte.github.io/astro/ (une minute après chaque publication)."))),
    h("div", { style: "display:flex;gap:8px;margin-top:14px" },
      h("button", { class: "ghost", onclick: () => go(false) }, "Fabriquer et voir en local"),
      h("button", { onclick: () => go(true) }, "Publier sur GitHub"),
      h("div", { class: "spacer" }),
      h("button", { class: "ghost", onclick: closeDlg }, "Fermer")),
    etat));
}
