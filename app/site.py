"""Site web statique de « Mes travaux », à publier (GitHub Pages ou n'importe quel hébergement de fichiers).

construire() fabrique un dossier autonome : index.html (galerie par cible, page de chaque cible, visionneuse), les
images finales redimensionnées pour le web (colorisée, naturelle, stack brut ; dernière version de chacune), leurs
vignettes et les fiches PDF. Jamais de FIT, de TIFF ni de NOTES. Incrémental : une image déjà convertie et plus récente
que l'original n'est pas refaite. publier() envoie le dossier sur un dépôt git (branche main) : GitHub Pages le sert.
L'appli n'est jamais exposée : le site ne contient que des fichiers."""
import html
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from . import config, galerie

LARGEUR_WEB = 2560
LARGEUR_VIGNETTE = 640
GARDER = ("colorise", "naturel", "stack_brut")
ETIQUETTE = {"colorise": "Colorisée", "naturel": "Naturelle", "stack_brut": "Stack brut"}


def dossier():
    cfg = config.load()
    d = str(cfg.get("site_dossier") or "").strip()
    return Path(d) if d else Path(cfg["astro_root"]) / "site_galerie"


def _slug(t):
    s = re.sub(r"[^a-z0-9]+", "-", t.lower().replace("é", "e").replace("è", "e")).strip("-")
    return s or "cible"


def _jpeg(src, dst, largeur):
    from PIL import Image
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(src) as im:
        im.draft("RGB", (largeur, largeur))
        im = im.convert("RGB")
        im.thumbnail((largeur, largeur))
        im.save(dst, "JPEG", quality=88 if largeur > 1000 else 82, optimize=True, progressive=True)
    return True


def _copie(src, dst):
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime and dst.stat().st_size == src.stat().st_size:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def construire(dest=None, titre="", log=print):
    """Fabrique le site dans `dest`. Retourne un résumé."""
    dest = Path(dest or dossier())
    dest.mkdir(parents=True, exist_ok=True)
    base = galerie.racine()
    data = galerie.explorer()
    if data.get("erreur"):
        raise ValueError(data["erreur"])
    cibles, faits, gardes, slugs = [], 0, set(), set()
    for c in data["cibles"]:
        sc = _slug(c["cible"])
        while sc in slugs:
            sc += "-2"
        slugs.add(sc)
        travaux = []
        for k, t in enumerate(c["travaux"]):
            st = f"{sc}/{k + 1}" if len(c["travaux"]) > 1 else sc
            imgs, vus = [], set()
            for im in t["images"]:                          # déjà triées : dernière version d'abord
                if im["genre"] not in GARDER or im["genre"] in vus:
                    continue
                vus.add(im["genre"])
                src = base / im["chemin"]
                web = f"img/{st}/{im['genre']}.jpg"
                vig = f"img/{st}/{im['genre']}_vignette.jpg"
                faits += _jpeg(src, dest / web, LARGEUR_WEB) + _jpeg(src, dest / vig, LARGEUR_VIGNETTE)
                gardes.update({web, vig})
                imgs.append({"src": web, "vignette": vig, "titre": ETIQUETTE[im["genre"]]})
            imgs.sort(key=lambda i: list(ETIQUETTE.values()).index(i["titre"]))
            fiches = []
            for f in t["fiches"][:1]:
                rel = f"fiches/{st.replace('/', '_')}.pdf"
                faits += _copie(base / f["chemin"], dest / rel)
                gardes.add(rel)
                fiches.append(rel)
            if not imgs and not fiches:
                continue
            fa = t.get("faits") or {}
            infos = [x for x in (fa.get("appareil"), fa.get("integration") and f"intégration {fa['integration']}",
                                 fa.get("poses") and f"{fa['poses']} poses", fa.get("ciel") and f"ciel {fa['ciel']}") if x]
            travaux.append({"lieu": t["lieu"], "date": t["date"] or t["modifie"], "infos": infos, "images": imgs,
                            "fiche": fiches[0] if fiches else None})
            log(f"site : {c['cible']} ({len(imgs)} image(s){', fiche' if fiches else ''})")
        if travaux:
            cibles.append({"cible": c["cible"], "slug": sc, "type": c.get("type") or "", "travaux": travaux,
                           "couverture": travaux[0]["images"][0]["vignette"] if travaux[0]["images"] else None})
    # fichiers d'une cible retirée depuis : supprimés (le dossier du site n'appartient qu'à l'appli)
    for sous in ("img", "fiches"):
        for f in (dest / sous).rglob("*") if (dest / sous).exists() else []:
            if f.is_file() and f.relative_to(dest).as_posix() not in gardes:
                f.unlink()
    titre = (titre or config.load().get("site_titre") or "Mes astrophotographies").strip()
    (dest / "index.html").write_text(_page(titre, cibles), encoding="utf-8")
    (dest / ".nojekyll").write_text("")                  # GitHub Pages : servir les fichiers tels quels
    taille = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file() and ".git" not in f.parts)
    return {"dossier": str(dest), "cibles": len(cibles), "travaux": sum(len(c["travaux"]) for c in cibles),
            "convertis": int(faits), "taille_mo": round(taille / 1e6, 1)}


def _git(args, cwd, log):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    for line in (r.stdout + r.stderr).strip().splitlines()[-6:]:
        log(f"git {args[0]} : {line}")
    return r


def normaliser_depot(depot):
    """Accepte aussi l'adresse du site (https://compte.github.io/depot/) ou celle de la page du dépôt
    (https://github.com/compte/depot) : renvoie l'adresse git (https://github.com/compte/depot.git)."""
    d = str(depot or "").strip()
    m = re.match(r"^https?://([\w-]+)\.github\.io/([\w.-]+?)/?$", d)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}.git"
    m = re.match(r"^https?://github\.com/([\w-]+)/([\w.-]+?)(\.git)?/?$", d)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}.git"
    return d


def publier(depot, dest=None, titre="", log=print):
    """Construit puis pousse le site sur `depot` (URL git, ex. https://github.com/<compte>/astro.git), branche main."""
    depot = normaliser_depot(depot)
    if not re.match(r"^(https://|git@|file://)[\w.@:/~-]+$", depot):
        raise ValueError("adresse du dépôt invalide (ex. : https://github.com/ton-compte/astro.git)")
    if shutil.which("git") is None:
        raise ValueError("git n'est pas installé sur ce PC (Git for Windows : https://git-scm.com)")
    res = construire(dest, titre, log)
    d = Path(res["dossier"])
    if not (d / ".git").exists():
        _git(["init", "-b", "main"], d, log)
    r = _git(["remote", "get-url", "origin"], d, log)
    if r.returncode != 0:
        _git(["remote", "add", "origin", depot], d, log)
    elif r.stdout.strip() != depot:
        _git(["remote", "set-url", "origin", depot], d, log)
    _git(["add", "-A"], d, log)
    if _git(["diff", "--cached", "--quiet"], d, log).returncode == 0:
        log("site : rien de nouveau à publier")
        res["publie"] = "inchangé"
        return res
    _git(["-c", "user.name=Atelier astro", "-c", "user.email=atelier@localhost", "commit", "-q", "-m",
          f"Site mis à jour le {datetime.now():%Y-%m-%d %H:%M}"], d, log)
    r = _git(["push", "-u", "origin", "main"], d, log)
    if r.returncode != 0:
        raise ValueError("envoi refusé par le dépôt : vérifie l'adresse et que tu es connecté à GitHub sur ce PC "
                         "(un premier « git push » à la main ouvre la fenêtre de connexion). Détail : "
                         + (r.stderr.strip().splitlines() or ["?"])[-1])
    res["publie"] = "envoyé"
    return res


def _page(titre, cibles):
    data = json.dumps({"titre": titre, "cibles": cibles, "maj": f"{datetime.now():%d/%m/%Y}"}, ensure_ascii=False)
    data = data.replace("</", "<\\/")
    return PAGE.replace("{{TITRE}}", html.escape(titre)).replace("{{DATA}}", data)


PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITRE}}</title>
<style>
:root { --bg:#0b0f1a; --panel:#121829; --line:#263049; --ink:#e6e9f2; --muted:#8b94ab; --accent:#7c5cff; --accent2:#3fa6ff; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 "Segoe UI", system-ui, -apple-system, sans-serif; }
header { padding:28px 24px 8px; max-width:1300px; margin:0 auto; }
header h1 { margin:0; font-size:26px; letter-spacing:.3px; }
header p { margin:4px 0 0; color:var(--muted); font-size:13px; }
main { max-width:1300px; margin:0 auto; padding:16px 24px 60px; }
a { color:var(--accent2); }
.grille { display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:18px; }
.carte { background:var(--panel); border:1px solid var(--line); border-radius:12px; overflow:hidden; cursor:pointer;
  text-decoration:none; color:inherit; transition:transform .12s, border-color .12s; display:block; }
.carte:hover { transform:translateY(-2px); border-color:var(--accent); }
.carte .img { aspect-ratio:4/3; background:#000; overflow:hidden; }
.carte img { width:100%; height:100%; object-fit:cover; display:block; }
.carte .leg { padding:10px 12px 12px; }
.carte b { font-size:16px; display:block; }
.muted { color:var(--muted); font-size:13px; }
.retour { display:inline-block; margin-bottom:12px; }
h2 { margin:6px 0 2px; font-size:24px; }
.travail { margin:20px 0 34px; padding-bottom:24px; border-bottom:1px solid var(--line); }
.travail h3 { margin:0 0 2px; font-size:17px; }
.images { display:flex; flex-wrap:wrap; gap:14px; margin-top:12px; }
.images figure { margin:0; cursor:zoom-in; }
.images img { height:240px; max-width:100%; border-radius:10px; border:1px solid var(--line); display:block; }
.images figcaption { text-align:center; color:var(--muted); font-size:13px; margin-top:4px; }
.fiche { display:inline-block; margin-top:12px; padding:7px 14px; border-radius:8px; background:var(--accent); color:#fff; text-decoration:none; }
.lb { position:fixed; inset:0; background:rgba(3,5,10,.94); display:flex; flex-direction:column; z-index:10; }
.lb .bar { display:flex; align-items:center; gap:10px; padding:10px 14px; color:var(--muted); font-size:13px; }
.lb .bar span { flex:1; }
.lb button { font:inherit; color:var(--ink); background:transparent; border:1px solid var(--line); border-radius:8px; padding:5px 12px; cursor:pointer; }
.lb .corps { flex:1; display:flex; align-items:center; justify-content:center; overflow:hidden; padding:8px; }
.lb img { max-width:100%; max-height:100%; object-fit:contain; }
footer { text-align:center; color:var(--muted); font-size:12px; padding:20px; }
@media (max-width:700px) { header, main { padding-left:16px; padding-right:16px; } .images img { height:150px; } }
</style>
</head>
<body>
<header><h1 id="titre"></h1><p id="sous"></p></header>
<main id="app"></main>
<footer>Traité avec Siril · Atelier astro</footer>
<script>
const D = {{DATA}};
const T = { nebuleuse: "nébuleuse", galaxie: "galaxie", amas: "amas" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
document.getElementById("titre").textContent = D.titre;
document.title = D.titre;
document.getElementById("sous").textContent = `${D.cibles.length} cible(s) · mis à jour le ${D.maj}`;
function grille() {
  return `<div class="grille">${D.cibles.map(c => { const t = c.travaux[0];
    return `<a class="carte" href="#${esc(c.slug)}"><div class="img">${c.couverture ? `<img loading="lazy" src="${esc(c.couverture)}" alt="${esc(c.cible)}">` : ""}</div>
      <div class="leg"><b>${esc(c.cible)}</b><span class="muted">${[T[c.type] || c.type, t.lieu, t.date].filter(Boolean).map(esc).join(" · ")}</span></div></a>`; }).join("")}</div>`;
}
function page(c) {
  return `<a class="retour" href="#">← Toutes les cibles</a><h2>${esc(c.cible)}</h2>` + c.travaux.map((t, k) =>
    `<section class="travail"><h3>${[t.lieu, t.date].filter(Boolean).map(esc).join(" — ")}</h3>
     <div class="muted">${t.infos.map(esc).join(" · ")}</div>
     <div class="images">${t.images.map((im, i) => `<figure data-t="${k}" data-i="${i}"><img loading="lazy" src="${esc(im.vignette)}" alt="${esc(im.titre)}"><figcaption>${esc(im.titre)}</figcaption></figure>`).join("")}</div>
     ${t.fiche ? `<a class="fiche" href="${esc(t.fiche)}" target="_blank">Fiche PDF</a>` : ""}</section>`).join("");
}
let lb = null;
function ouvrir(c, k, i) {
  const ims = c.travaux[k].images;
  lb = document.createElement("div"); lb.className = "lb";
  lb.innerHTML = `<div class="bar"><span></span><button data-a="-1">←</button><button data-a="1">→</button><button data-a="x">Fermer ✕</button></div><div class="corps"><img alt=""></div>`;
  const voir = (j) => { i = (j + ims.length) % ims.length; lb.querySelector("img").src = ims[i].src;
    lb.querySelector("span").textContent = `${c.cible} — ${ims[i].titre} (${i + 1}/${ims.length})`; };
  lb.addEventListener("click", (e) => { const a = e.target.dataset.a; if (a === "x" || e.target.classList.contains("corps")) fermer(); else if (a) voir(i + +a); });
  lb._k = (e) => { if (e.key === "Escape") fermer(); else if (e.key === "ArrowRight") voir(i + 1); else if (e.key === "ArrowLeft") voir(i - 1); };
  document.addEventListener("keydown", lb._k);
  document.body.append(lb); voir(i);
}
function fermer() { if (!lb) return; document.removeEventListener("keydown", lb._k); lb.remove(); lb = null; }
function rendre() {
  fermer();
  const app = document.getElementById("app");
  const c = D.cibles.find(x => x.slug === decodeURIComponent(location.hash.slice(1)));
  app.innerHTML = c ? page(c) : grille();
  if (c) app.querySelectorAll("figure").forEach(f => f.onclick = () => ouvrir(c, +f.dataset.t, +f.dataset.i));
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", rendre);
rendre();
</script>
</body>
</html>
"""
