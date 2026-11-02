"""Phase 2 : étirement + neutralisation, StarX, piste secondaire (mode B), étoiles, image naturelle (post-2-etoiles.md)."""
import shutil
import time

import numpy as np

from .. import checks, config, fitsio, outils
from .base import P, Step
from .lineaire import s50pro_correction, tool


def linear_src(p):
    return p.latest("nxt", "bxt", "spcc", "bge", "crop")


def controle_lines(ctx, path, extra=()):
    try:
        txt = ctx.py("controle.py", ["fit", path, *extra], check=False)
        return [l.strip() for l in txt.splitlines() if l.startswith(("ATTENTION", "BILAN"))]
    except Exception as e:
        return [f"controle.py indisponible : {e}"]


class Etirement(Step):
    id, phase, kind = "P5", "2 · Étirement et étoiles", "creatif"
    title = "Étirement et fond du ciel"
    help = ("Rend l'image visible et règle la luminosité des tons moyens : doux (fond cible 0.15), standard (0.25) ou "
            "poussé (0.35). Un fond cible plus haut éclaire l'intérieur de la nébuleuse et donne de la profondeur ; un "
            "fond très noir (0.07) écrase ces tons moyens. Pour un ciel plus sombre, mieux vaut un étirement standard puis "
            "l'étape « Noirs du fond », qui n'assombrit que le ciel. Autres méthodes : courbe calée sur le niveau du fond (« mtf »), « autoghs » qui ménage un noyau "
            "très brillant, ou Statistical Stretch qui fait tout automatiquement. Le fond est ensuite remis au gris "
            "neutre, canal par canal ; sans cela il sortirait teinté.")
    params = [
        P("methode", "Méthode", "choice", "autostretch",
          choices=[["autostretch", "autostretch lié"], ["mtf", "mtf calé sur le fond"], ["autoghs", "autoghs (noyau brillant)"],
                   ["statistical", "Statistical Stretch"]]),
        P("targetbg", "Fond cible", "float", 0.25, 0.02, 0.4, 0.01, show_if={"methode": ["autostretch"]},
          help="0.15 doux · 0.25 standard · 0.35 poussé (tons moyens de l'objet plus lumineux) · 0.07 fond très noir"),
        P("shadows", "Écrêtage des ombres (sigma)", "float", -2.8, -5, 0, 0.1, show_if={"methode": ["autostretch"]}),
        P("fond", "Fond", "choice", "noir", choices=[["noir", "noir (b = M)"], ["neutre", "neutre (b = 0.97 M)"]],
          show_if={"methode": ["mtf"]}),
        P("m", "Tons moyens m (plus petit = plus fort)", "float", 0.002, 0.0002, 0.1, 0.0002, show_if={"methode": ["mtf"]}),
        P("ghs_amount", "Force autoghs", "float", 145, 20, 300, 5, show_if={"methode": ["autoghs"]}),
        P("ghs_b", "b (autoghs)", "float", 5, 0, 15, 0.5, show_if={"methode": ["autoghs"]}),
        P("ss_median", "Médiane cible", "float", 0.25, 0.05, 0.5, 0.01, show_if={"methode": ["statistical"]},
          help="0.07 noir · 0.10 gris très sombre · 0.25 gris clair"),
        P("ss_sigma", "Sigma", "float", 5, 1, 10, 0.5, show_if={"methode": ["statistical"]}),
        P("mesure", "Neutraliser d'après", "choice", "ciel",
          choices=[["ciel", "le ciel seul (conseillé)"], ["image", "l'image entière (méthode d'origine)"]],
          help="quand la nébuleuse occupe une grande part du cadre, sa couleur fausse la mesure sur l'image entière "
               "et le fond sort teinté (cyan pour une nébuleuse rouge)"),
    ]
    # doux / standard / poussé, comme le pipeline : un fond cible plus haut éclaire les tons moyens de la nébuleuse
    # (« lumière intérieure », profondeur) ; 0.07 écrase ces tons moyens dans le noir
    default_variants = [{"methode": "autostretch", "targetbg": 0.15}, {"methode": "autostretch", "targetbg": 0.25},
                        {"methode": "autostretch", "targetbg": 0.35}]
    preview_key = "etire_neutre"
    linear = False
    canonical = {"etire": "{T}_etire.fit", "etire_neutre": "{T}_etire_neutre.fit"}

    def ready(self, p):
        return (linear_src(p) is not None, "aucune image linéaire validée (phase 1)")

    def run(self, ctx, prm, tag):
        p = ctx.p
        src = linear_src(p)
        out = ctx.out(tag, "etire")
        m = prm["methode"]
        info = []
        if m == "autostretch":
            cmd = [f"autostretch -linked {prm['shadows']} {prm['targetbg']}"]
        elif m == "mtf":
            d, _ = fitsio.read(src)
            M = float(np.mean([np.median(d[c][d[c] > 0]) for c in range(d.shape[0])]))
            b = M if prm["fond"] == "noir" else M * 0.97
            cmd = [f"mtf {b:.5f} {prm['m']} 1"]
            info.append(f"M (médiane du fond) = {M:.5f} → mtf {b:.5f} {prm['m']} 1")
        elif m == "autoghs":
            cmd = [f"autoghs 0 {prm['ghs_amount']} -b={prm['ghs_b']}"]
        else:
            cmd = [f'pyscript "{ctx.cfg["script_statstretch"]}" -median {prm["ss_median"]} -sigma {prm["ss_sigma"]} -linked']
        tool(ctx, src, out, cmd, "etirement")
        d, h = fitsio.read(out)
        mask = fitsio.sky_mask(d) if prm.get("mesure", "ciel") == "ciel" else None
        neu, before, off, after = fitsio.neutralize(d, mask)
        out2 = ctx.out(tag, "etire_neutre")
        fitsio.write(out2, neu, h)
        zeros = [round(float((d[c] <= 0).mean() * 100), 1) for c in range(d.shape[0])]
        info += [f"Médianes étirées R/V/B (zéros compris, {'ciel seul' if mask is not None else 'image entière'}) : {before}",
                 f"Décalages appliqués : {off}",
                 f"Après neutralisation : {after}", f"Pixels à zéro par canal : {zeros} %"]
        if max(after) - min(after) > 10:
            info.append("ATTENTION : médianes encore écartées de plus de 10 unités.")
        if min(off) < 0 and max(zeros) > 2:
            info.append("ATTENTION : décalage négatif sur un canal déjà riche en zéros (point noir différent selon le canal).")
        info += checks.crushed_blacks(d)
        return {"outputs": {"etire": ctx.rel(out), "etire_neutre": ctx.rel(out2)}, "info": info, "linear": False}

    def notes(self, p, st):
        x = st["params"]
        m = x.get("methode")
        d = {"autostretch": f"autostretch lié {x.get('shadows')} {x.get('targetbg')}",
             "mtf": f"mtf calé sur le fond ({x.get('fond')}), m {x.get('m')}",
             "autoghs": f"autoghs 0 {x.get('ghs_amount')} -b={x.get('ghs_b')}",
             "statistical": f"Statistical Stretch médiane {x.get('ss_median')}, sigma {x.get('ss_sigma')}"}.get(m, m)
        return f"Étirement : {d}, puis fond neutralisé par canal"


def find_new_stars(p, since):
    cands = [f for d in (p.root, p.root / "essais") for f in d.glob("stars_*") if f.stat().st_mtime >= since - 1]
    return max(cands, key=lambda f: f.stat().st_mtime) if cands else None


def starx(ctx, src, out_starless, out_stars, name="starx"):
    """Séparation des étoiles sur l'image étirée, avec l'outil choisi. StarXTerminator écrit son calque d'étoiles
    (--stars --unscreen) ; sinon le calque est déduit : étoiles = 1 - (1 - image) / (1 - sans étoiles), l'inverse
    exact de la fusion en écran utilisée plus loin."""
    t0 = time.time()
    tool(ctx, src, out_starless, outils.commandes(ctx.cfg, "etoiles"), name)
    a, h = fitsio.read(out_starless)
    b, _ = fitsio.read(src)
    if np.allclose(a[:, ::8, ::8], b[:, ::8, ::8], atol=1e-5):
        raise RuntimeError(f"le calque sans étoiles est identique à l'image d'entrée : {outils.nom(ctx.cfg, 'etoiles')} "
                           "n'a rien fait (installation, licence ?)")
    st = find_new_stars(ctx.p, t0) if outils.choix(ctx.cfg, "etoiles") == "rcastro" else None
    if st:
        shutil.move(str(st), str(out_stars))
    else:
        stars = np.clip(1 - (1 - b) / np.maximum(1 - a, 1e-4), 0, 1)
        stars[stars < 1e-4] = 0
        fitsio.write(out_stars, stars, h)
    return out_starless, out_stars


class StarX(Step):
    id, phase = "P6", "2 · Étirement et étoiles"
    help = ("Sépare les étoiles du reste de l'image, pour les traiter à part (outil : Réglages > Outils). Sur une galaxie, vérifie "
            "sur le deuxième aperçu (le calque d'étoiles) qu'aucun morceau de la galaxie n'y est parti. "
            "« Passer l'étape » = garder les étoiles telles quelles ; les couleurs se feront alors sur l'image entière.")
    params = []
    preview_key = "starless"
    linear = False

    @property
    def title(self):
        return f"Séparation des étoiles ({outils.nom(config.load(), 'etoiles')})"

    def applies(self, p):
        return outils.sans_objet(config.load(), "etoiles")
    optional = True
    canonical = {"starless": "{T}_starless.fit", "stars_raw": "{T}_stars_brut.fit"}
    produces = ("starless", "stars_raw", "stars")

    def ready(self, p):
        return (p.file("etire_neutre") is not None, "valider d'abord l'étirement (P5)")

    def run(self, ctx, prm, tag):
        a, b = starx(ctx, ctx.p.file("etire_neutre"), ctx.out(tag, "starless"), ctx.out(tag, "stars"))
        img = ctx.out(tag, "stars_apercu", ".jpg", folder="apercus")
        fitsio.preview(b, img, False)
        return {"outputs": {"starless": ctx.rel(a), "stars_raw": ctx.rel(b)}, "images": [ctx.rel(img)], "info": []}

    def notes(self, p, st):
        return "Séparation des étoiles : StarXTerminator --stars --unscreen, sur l'image étirée"


class PisteSecondaire(Step):
    id, phase = "P6B", "2 · Étirement et étoiles"
    title = "Piste secondaire (mode B, expérimental)"
    help = ("Mode B seulement : prépare le second stack avec le même cadrage. Pour une nébuleuse, on en tire les étoiles "
            "de l'IRCUT, aux couleurs plus justes ; pour une galaxie, les régions HII du LP, à ajouter à l'étape Couleurs. "
            "Pas encore essayé sur tes données.")
    params = [P("spcc", "SPCC sur l'IRCUT (nébuleuse)", "bool", True)]
    linear = False
    canonical = {"stars_ir": "{T}_IR_stars.fit", "lp_starless": "{T}_LP_starless.fit"}

    def applies(self, p):
        return (p.mode == "B", "seulement en mode B (deux stacks séparés)")

    def ready(self, p):
        return (p.file("stack2") is not None and p.state["facts"].get("crop"), "il faut le second stack et le recadrage")

    def compose_preview(self, ctx, outputs, tag=""):
        k = "stars_ir" if "stars_ir" in outputs else "lp_starless"
        return ctx.p.abs(outputs[k])

    def run(self, ctx, prm, tag):
        p, cfg = ctx.p, ctx.cfg
        x, y, w, h = p.state["facts"]["crop"]
        src = p.file("stack2")
        H = fitsio.header(src).get("NAXIS2")
        ys = y if cfg.get("crop_y_origin", "haut") == "haut" else H - y - h
        c = ctx.out(tag, "crop2")
        tool(ctx, src, c, ["boxselect -clear", f"crop {x} {ys} {w} {h}"], "secondaire_crop")
        main_dims = fitsio.header(p.file("crop"))
        dims = fitsio.header(c)
        if (dims.get("NAXIS1"), dims.get("NAXIS2")) != (main_dims.get("NAXIS1"), main_dims.get("NAXIS2")):
            raise RuntimeError("le second stack recadré n'a pas les dimensions de T_crop : arrêt")
        bge = ctx.out(tag, "bge2")
        if outils.actif(cfg, "fond"):
            tool(ctx, c, bge, outils.commandes(cfg, "fond", 1.0), "secondaire_bge")
        else:
            shutil.copy(str(c), str(bge))
        info = []
        if p.type == "nebuleuse":
            cur = bge
            if prm["spcc"]:
                sp = ctx.out(tag, "spcc2")
                cat = " -catalog=localgaia" if cfg.get("spcc_catalog_local", True) else ""
                from .lineaire import principal_profile
                _, prof = principal_profile(p)
                sensor = prof.get("capteur_spcc")
                cmd = (f'spcc "-oscsensor={sensor}" "-oscfilter={prof.get("filtre_spcc") or "UV/IR Block"}"{cat} '
                       '"-whiteref=Average Spiral Galaxy"') if sensor else "pcc" + cat
                tool(ctx, bge, sp, ["platesolve -force", cmd], "secondaire_spcc")
                if prof.get("correction") == "s50pro":
                    d, hh = fitsio.read(sp)
                    d2, txt = s50pro_correction(d)
                    fitsio.write(sp, d2, hh)
                    info.append(txt)
                cur = sp
            bx = ctx.out(tag, "bxt2")
            if outils.actif(cfg, "nettete"):
                tool(ctx, cur, bx, outils.commandes(cfg, "nettete", 0.75, ss=0.4, ansp=True), "secondaire_bxt")
            else:
                shutil.copy(str(cur), str(bx))
            et = ctx.out(tag, "etire2")
            tool(ctx, bx, et, ["autostretch -linked"], "secondaire_etire")
            _, stars = starx(ctx, et, ctx.out(tag, "starless2"), ctx.out(tag, "stars_ir"), "secondaire_starx")
            info.append("Étoiles IRCUT prêtes : à comparer aux étoiles LP à l'étape Étoiles.")
            return {"outputs": {"stars_ir": ctx.rel(stars)}, "info": info}
        nx = ctx.out(tag, "nxt2")
        if outils.actif(cfg, "debruitage"):
            tool(ctx, bge, nx, outils.commandes(cfg, "debruitage", 0.8), "secondaire_nxt")
        else:
            shutil.copy(str(bge), str(nx))
        et = ctx.out(tag, "etire2")
        tool(ctx, nx, et, ["autostretch -linked"], "secondaire_etire")
        sl, _ = starx(ctx, et, ctx.out(tag, "lp_starless"), ctx.out(tag, "stars_lp2"), "secondaire_starx")
        info.append("Calque sans étoiles du LP prêt : option « Régions HII du LP » à l'étape Couleurs.")
        return {"outputs": {"lp_starless": ctx.rel(sl)}, "info": info}

    def notes(self, p, st):
        return ("Piste secondaire (mode B) : étoiles de l'IRCUT" if p.type == "nebuleuse"
                else "Piste secondaire (mode B) : régions HII du LP")


def attenuer_halos(path, force, seuil=0.35):
    """Atténue la partie diffuse du calque d'étoiles (sous `seuil`) : les cœurs, au-dessus, sont inchangés ; les halos
    et le pied des étoiles sont abaissés d'autant plus qu'ils sont faibles. Écrit le fichier en place."""
    d, h = fitsio.read(path)
    mx = d.max(0)
    halo = (mx > 0.02) & (mx < 0.2)
    avant = float(d[:, halo].sum()) if halo.any() else 0.0
    # exposant 4 x force : 0.25 -> 1 (léger), 0.5 -> 2 (moyen, le plateau à 0.1 tombe à ~8 %), 1 -> 4 (comme la
    # réduction par puissance sur les halos) ; au-dessus du seuil (cœurs), rien ne change
    f = np.clip(mx / seuil, 0, 1) ** (4.0 * float(force))
    d2 = (d * f[None]).astype(np.float32)
    fitsio.write(path, d2, h)
    apres = float(d2[:, halo].sum()) if halo.any() else 0.0
    return [f"Halos atténués (force {force:.2f}) : lumière des halos diffus {100 * apres / max(avant, 1e-9):.0f} % de "
            "l'original ; cœurs des étoiles inchangés"]


class Etoiles(Step):
    id, phase, kind = "P7", "2 · Étirement et étoiles", "creatif"
    title = "Gestion des étoiles"
    help = ("Tu choisis combien d'étoiles garder : un nombre dans le ciel et un dans la nébuleuse ou la galaxie. Les "
            "plus brillantes sont gardées telles quelles, une par une, sans emmener leurs petites voisines. Si un amas "
            "d'étoiles compte (ex. au cœur d'une nébuleuse), protège-le : dessine un cercle autour sur l'image, ses étoiles "
            "les plus brillantes sont gardées en plus du nombre choisi. Autres choix : réduire toutes les "
            "étoiles, les garder ou les supprimer. Le champ d'étoiles est dense à ce stade, c'est normal. Repère : sur ton "
            "NGC 281, 1500 étoiles dans le ciel et 100 dans l'objet avaient été retenues.")
    params = [
        P("methode", "Méthode", "choice", "selection",
          choices=[["selection", "Sélection étoile par étoile"], ["puissance", "Réduction par puissance"],
                   ["garder", "Garder telles quelles"], ["supprimer", "Supprimer"]]),
        P("source", "Calque d'étoiles", "choice", "principal", choices=[["principal", "stack principal"], ["ir", "IRCUT (mode B)"]],
          help="mode B nébuleuse : étoiles LP ou IRCUT"),
        P("n_ciel", "Étoiles gardées dans le ciel", "int", 1500, 0, 20000, 50, show_if={"methode": ["selection"]}),
        P("n_objet", "Étoiles gardées dans l'objet", "int", 100, 0, 5000, 10, show_if={"methode": ["selection"]}),
        P("diversite", "Diversité des tailles", "float", 0.4, 0, 0.9, 0.05, show_if={"methode": ["selection"]},
          help="même nombre d'étoiles, mais une part prise parmi les plus faibles, réparties sur toute la gamme : des "
               "petites étoiles entre les grosses, comme dans un vrai champ. 0 = seulement les plus brillantes (toutes "
               "de grande taille) · 0.4 = 40 % de petites · 0.7 = surtout des petites"),
        P("plancher", "Plancher", "float", 0.08, 0.01, 0.3, 0.01, show_if={"methode": ["selection"]}),
        P("pic_min", "Pic minimal", "float", 0.20, 0.05, 0.6, 0.01, show_if={"methode": ["selection"]}),
        P("halo", "Halo recousu (px)", "int", 11, 0, 25, 1, show_if={"methode": ["selection"]}),
        P("amas", "Amas protégé (rempli par le cercle dessiné)", "text", "", show_if={"methode": ["selection"]},
          help="centre x, centre y, rayon, nombre d'étoiles gardées en plus — se remplit tout seul avec l'outil « Protéger un amas »"),
        P("k", "Exposant k", "float", 2.5, 1.0, 6, 0.1, show_if={"methode": ["puissance"]},
          help="1.5 léger · 2.5 moyen · 4 fort"),
        P("halos", "Atténuer les halos", "float", 0.0, 0.0, 1.0, 0.05, show_if={"methode": ["selection", "garder"]},
          help="réduit le plateau délavé autour des étoiles (pied des étoiles éclairci par l'étirement, qui ressort sur "
               "un ciel assombri en P6N ; halo du filtre LP) sans toucher à leur cœur ; 0 = intact · 0.25 léger · "
               "0.5 moyen · 1 fort"),
    ]
    # peu d'étoiles d'abord : sur un champ de Voie lactée, quelques centaines d'étoiles laissent la nébuleuse
    # dominer et donnent de la profondeur
    default_variants = [{"methode": "selection", "n_ciel": 300, "n_objet": 100, "halos": 0.5},
                        {"methode": "selection", "n_ciel": 300, "n_objet": 100, "halos": 0},
                        {"methode": "selection", "n_ciel": 1500, "n_objet": 100, "halos": 0.5},
                        {"methode": "puissance", "k": 2.5}]
    preview_key = "stars"
    linear = False
    interaction = "point"
    reference_step = "P6"
    canonical = {"stars": "{T}_stars.fit"}

    def applies(self, p):
        if p6_passe(p):
            return False, "étoiles gardées dans l'image (séparation passée ou sans outil)"
        return True, ""

    def ready(self, p):
        return (p.file("starless") is not None and p.file("stars_raw") is not None, "valider d'abord StarX (P6)")

    def dyn_defaults(self, p):
        # mode B nébuleuse : c'est tout l'intérêt de la piste IRCUT, ses étoiles n'ont pas le halo rose du filtre LP
        if p.mode == "B" and p.type == "nebuleuse" and p.file("stars_ir"):
            return {"source": "ir"}
        return {}

    def compose_preview(self, ctx, outputs, tag=""):
        sl, hdr = fitsio.read(starless_layer(ctx.p))
        if "stars" in outputs:
            st, _ = fitsio.read(ctx.p.abs(outputs["stars"]))
            sl = fitsio.screen(sl, st)
        out = ctx.out(tag, "fusion_apercu")
        fitsio.write(out, sl, hdr)
        return out

    def run(self, ctx, prm, tag):
        p = ctx.p
        src = p.file("stars_ir") if (prm["source"] == "ir" and p.file("stars_ir")) else p.file("stars_raw")
        starless = p.file("starless")
        out = ctx.out(tag, "stars")
        info = []
        m = prm["methode"]
        if m == "selection":
            args = [src, starless, out, prm["n_ciel"], prm["n_objet"], 0.97, prm["plancher"], prm["pic_min"], 0, prm["halo"]]
            if prm["amas"].strip():
                x, y, r, n = [float(v) for v in prm["amas"].split(",")[:4]]
                hdr = fitsio.header(src)
                row = fitsio.y_top_to_row(y, hdr["NAXIS2"], hdr)
                if not (0 <= x < hdr["NAXIS1"] and 0 <= row < hdr["NAXIS2"]):
                    raise ValueError(f"amas hors de l'image ({int(x)}, {int(y)}) : l'image fait {hdr['NAXIS1']}x{hdr['NAXIS2']} px")
                args.append(f"{int(x)},{row},{int(r)},{int(n)}")
                info.append(f"Amas : x {int(x)}, y {int(y)} depuis le haut = ligne FITS {row}, r {int(r)}, {int(n)} étoiles")
            args.append(f"--diversite={prm.get('diversite', 0)}")
            txt = ctx.py("etoiles_selection_pics.py", args)
            info += [l for l in txt.splitlines() if l.strip()][-4:]
            d, _ = fitsio.read(out)
            frac = float((d.max(0) > prm["plancher"]).mean() * 100)
            info.append(f"Pixels du calque au-dessus du plancher : {frac:.1f} %" +
                        (" — ATTENTION, au-delà de ~10 % : monter le plancher" if frac > 10 else ""))
            outputs = {"stars": ctx.rel(out)}
        elif m == "puissance":
            d, h = fitsio.read(src)
            fitsio.write(out, np.power(d, prm["k"]), h)
            outputs = {"stars": ctx.rel(out)}
        elif m == "garder":
            d, h = fitsio.read(src)
            fitsio.write(out, d, h)
            outputs = {"stars": ctx.rel(out)}
        else:
            outputs = {}
            info.append("Étoiles supprimées : le calque sans étoiles sera l'image finale.")
        if "stars" in outputs and m in ("selection", "garder") and prm.get("halos", 0) > 0:
            info += attenuer_halos(p.abs(outputs["stars"]), prm["halos"])
        if prm["source"] == "ir" and not p.file("stars_ir"):
            info.append("ATTENTION : étoiles IRCUT demandées mais pas encore préparées (étape P6B) : étoiles du stack principal utilisées.")
        if "stars" in outputs and src != p.file("stars_raw"):
            sl, _ = fitsio.read(starless)
            stv, _ = fitsio.read(p.abs(outputs["stars"]))
            ref_st, _ = fitsio.read(p.file("stars_raw"))
            info += checks.doubled_stars(fitsio.screen(sl, stv), ref=fitsio.screen(sl, ref_st))
        return {"outputs": outputs, "info": info, "linear": False}

    def on_validate(self, p, var):
        if "stars" not in var.get("outputs", {}):
            p.state["files"].pop("stars", None)

    def notes(self, p, st):
        prm = st.get("params", {})
        m = prm.get("methode")
        if m == "selection":
            s = (f"Étoiles : sélection étoile par étoile, ciel {prm.get('n_ciel')}, objet {prm.get('n_objet')}, diversité des tailles "
                 f"{prm.get('diversite', 0)}, plancher {prm.get('plancher')}, halo {prm.get('halo')}")
            s += f", amas {prm['amas']}" if prm.get("amas") else ""
        elif m == "puissance":
            s = f"Étoiles : réduction pow k={prm.get('k')}"
        else:
            s = f"Étoiles : {m}"
        if m in ("selection", "garder") and prm.get("halos"):
            s += f", halos atténués {prm['halos']}"
        if m != "supprimer" and prm.get("source") == "ir":
            s += ", étoiles IRCUT"
        return s


def starless_layer(p):
    """Calque sans étoiles en cours : avec les noirs retravaillés (P6N) s'ils ont été validés."""
    return p.latest("starless_noir", "starless")


def p6_passe(p):
    """Pas de séparation des étoiles : étape passée, ou aucun outil choisi (Réglages > Outils)."""
    return p.state["steps"].get("P6", {}).get("status") == "skipped" or not outils.actif(config.load(), "etoiles")


def layers(p):
    """(calque sans étoiles, calque d'étoiles ou None). StarX passé : image entière, pas de calque d'étoiles."""
    if p6_passe(p) or not p.file("starless"):
        return p.file("etire_neutre"), None
    st = p.state["steps"].get("P7", {})
    if st.get("status") in ("done", "stale") and "stars" not in (st.get("outputs") or {}):
        return starless_layer(p), None
    return starless_layer(p), p.file("stars")


class Naturel(Step):
    id, phase, kind = "P7T", "2 · Étirement et étoiles", "auto"
    title = "Image finale naturelle"
    help = ("Image sans étoiles et étoiles retenues réunies, sans aucune retouche de couleur. Elle sert de référence "
            "pour comparer les couleurs à l'étape suivante, et donne la version « naturelle » de l'export et de la fiche.")
    params = []
    preview_key = "naturel"
    linear = False
    canonical = {"naturel": "{T}_fusion_naturel.fit"}

    def ready(self, p):
        sl, _ = layers(p)
        ok = sl is not None and (p6_passe(p)
                                 or p.state["steps"].get("P7", {}).get("status") in ("done", "stale"))
        return ok, "valider d'abord les étoiles (P7) ou passer StarX"

    def run(self, ctx, prm, tag):
        p = ctx.p
        sl, st = layers(p)
        a, h = fitsio.read(sl)
        if st:
            b, _ = fitsio.read(st)
            a = fitsio.screen(a, b)
        out = ctx.out(tag, "naturel")
        fitsio.write(out, a, h)
        s = fitsio.stats(a)
        info = [f"Médianes R/V/B : {s['medianes']} · max {s['max']} · écrêtés {s['ecretes_pct']} %"]
        info += controle_lines(ctx, out, ["--etoiles", st] if st else [])
        return {"outputs": {"naturel": ctx.rel(out)}, "info": info}

    def notes(self, p, st):
        return "Image naturelle : calque sans étoiles neutralisé + étoiles retenues, fusion en écran"


class Noirs(Step):
    id, phase, kind, optional = "P6N", "2 · Étirement et étoiles", "creatif", True
    title = "Noirs du fond (nébuleuse seule)"
    help = ("Approfondit le noir du fond sur le calque sans étoiles : les étoiles ne sont pas touchées, donc pas de "
            "halos ternis ni d'étoiles faibles avalées. « Niveau du fond » fixe le gris du ciel visé (sur 255). "
            "« Protéger la nébuleuse » n'assombrit que le ciel, en épargnant progressivement les zones de l'objet et ses "
            "franges faibles. « Douceur » arrondit le pied de la courbe au lieu de couper net, pour garder le signal "
            "le plus faible. Trop noir = franges de nébulosité perdues et bruit du fond plus visible : les contrôles "
            "indiquent la part de signal faible perdue.")
    params = [
        P("niveau", "Niveau du fond visé (sur 255)", "float", 18, 2, 40, 1,
          help="25 léger (proche du pipeline, qui ne fait que neutraliser le fond) · 18 moyen · 12 noir ; voir la "
               "médiane du fond dans l'aperçu de référence"),
        P("proteger", "Protéger la nébuleuse", "bool", True),
        P("seuil_objet", "Début de la nébuleuse (percentile)", "float", 70, 40, 95, 1, show_if={"proteger": [True]},
          help="plus bas = protège davantage de zones faibles ; plus haut = assombrit plus près de l'objet"),
        P("douceur", "Douceur du pied de courbe", "float", 0.5, 0, 1, 0.05),
    ]
    default_variants = [{"niveau": 25}, {"niveau": 18}, {"niveau": 12}]
    preview_key = "starless_noir"
    linear = False
    reference_step = "P6"
    canonical = {"starless_noir": "{T}_starless_noir.fit"}
    produces = ("starless_noir",)

    def applies(self, p):
        return (not p6_passe(p), "étoiles gardées dans l'image (séparation passée ou sans outil) : rien à séparer")

    def ready(self, p):
        return (p.file("starless") is not None, "valider d'abord StarX (P6)")

    def run(self, ctx, prm, tag):
        import cv2
        p = ctx.p
        d, h = fitsio.read(p.file("starless"))
        L = d.mean(0)
        skym = fitsio.sky_mask(d)
        skies = np.array([float(np.median(d[c][skym])) for c in range(d.shape[0])])
        sky = float(skies.mean())
        target = prm["niveau"] / 255.0
        info = [f"Fond du ciel avant (R/V/B, ciel seul) : {' / '.join(f'{v * 255:.1f}' for v in skies)} sur 255 → visé "
                f"{prm['niveau']:.0f}/255 sur les trois canaux"]
        if target >= skies.min():
            info.append("Le fond est déjà plus sombre que le niveau visé sur au moins un canal : image inchangée "
                        "(baisse le niveau visé).")
            out = d
        else:
            # un point noir par canal : chaque canal du ciel arrive au même niveau, le fond reste (ou devient) neutre
            b = ((skies - target) / (1 - target))[:, None, None]
            y = (d - b) / (1 - b)
            s = max(prm["douceur"], 0.0) * 0.02
            if s > 0:                                               # pied de courbe arrondi (softplus) au lieu d'une coupe nette
                dark = np.clip(s * np.logaddexp(0, y / s), 0, 1)
            else:
                dark = np.clip(y, 0, 1)
            if prm["proteger"]:
                ls = cv2.GaussianBlur(L, (0, 0), 6)
                lo, hi = np.percentile(ls, prm["seuil_objet"]), np.percentile(ls, 99.5)
                w = np.clip((ls - lo) / max(hi - lo, 1e-6), 0, 1)
                w = w * w * (3 - 2 * w)                             # 0 dans le ciel, 1 dans l'objet
                out = dark * (1 - w) + d * w
                info.append(f"Nébuleuse protégée au-delà du {prm['seuil_objet']:.0f}e percentile "
                            f"({(w > 0.5).mean() * 100:.0f} % de l'image épargnée)")
            else:
                out = dark
            out = np.clip(out, 0, 1).astype(np.float32)
            # la courbe n'agit pas tout à fait pareil sur des canaux de bruit différent : petit recalage final du ciel
            out, _, off2, _ = fitsio.neutralize(out, skym)
            if max(abs(v) for v in off2) > 1:
                info.append(f"Recalage final du ciel par canal : {off2} ADU")
        o = ctx.out(tag, "starless_noir")
        fitsio.write(o, out, h)
        L2 = out.mean(0)
        after = [float(np.median(out[c][skym])) * 255 for c in range(out.shape[0])]
        info.append(f"Fond du ciel après (R/V/B) : {' / '.join(f'{v:.1f}' for v in after)} sur 255")
        # signal faible : pixels entre le 60e et le 85e percentile avant (franges de nébulosité, bras faibles)
        lo, hi = np.percentile(L, 60), np.percentile(L, 85)
        faint = (L > lo) & (L < hi)
        lost = float(((L2 < 1.5 / 255) & faint).sum() / max(faint.sum(), 1) * 100)
        sep_b = float(np.median(L[faint]) - sky)
        sep_a = float(np.median(L2[faint]) - np.median(L2))
        info.append(f"Signal faible : écart au fond {sep_b * 255:.1f} → {sep_a * 255:.1f} /255 ; {lost:.1f} % de ces pixels tombés au noir")
        if lost > 5:
            info.append(f"ATTENTION {lost:.0f} % des zones faibles sont devenues noires : franges de nébulosité perdues. "
                        "Remonte le niveau visé, augmente la douceur ou active la protection de la nébuleuse.")
        info += checks.crushed_blacks(out)
        info += checks.noise_change(p.file("starless"), o, "après assombrissement")
        return {"outputs": {"starless_noir": ctx.rel(o)}, "info": info}

    def notes(self, p, st):
        x = st["params"]
        return (f"Noirs du fond : niveau {x.get('niveau'):.0f}/255, douceur {x.get('douceur')}"
                + (f", nébuleuse protégée (percentile {x.get('seuil_objet'):.0f})" if x.get("proteger") else ""))


STEPS = [Etirement(), StarX(), Noirs(), PisteSecondaire(), Etoiles(), Naturel()]
