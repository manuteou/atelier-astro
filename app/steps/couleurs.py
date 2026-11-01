"""Phase 3 (1/4) : couleur des étoiles et couleurs du calque sans étoiles (post-3-couleurs-export.md).
Le réglage fin (P8F), la fusion et le débruitage final (P9, P10) et les retouches (P11) sont dans leurs modules."""
import numpy as np

from .. import checks, color_ops, fitsio
from .base import P, Step
from .etoiles import layers
from .lineaire import tool


def stars_final(p):
    _, st = layers(p)
    if st is None:
        return None
    return p.latest("stars_couleur") if p.state["steps"].get("P7BIS", {}).get("status") in ("done", "stale") else st


def galaxy_layer(p):
    sl, _ = layers(p)
    return sl


def fused_preview(ctx, g_path, tag, name="apercu"):
    g, h = fitsio.read(g_path)
    s = stars_final(ctx.p)
    if s:
        st, _ = fitsio.read(s)
        g = fitsio.screen(g, st)
    out = ctx.out(tag, name)
    fitsio.write(out, g, h)
    return out


GRADIENTS = {"rose": ("#b0306e", "#ffc4e4"), "rouge": ("#a01c1c", "#ff9a78"), "emeraude": ("#0f7a6a", "#a8f5e2")}


def sky_of(d):
    """Niveau du ciel (luminance) : médiane de la moitié la plus sombre ; sert à protéger le fond au réglage fin."""
    L = d[:3].mean(0)
    return float(np.median(L[fitsio.sky_mask(d)]))


def clipped_pct(d):
    return float((d[:3].max(0) >= 0.995).mean() * 100)


class CouleurEtoiles(Step):
    id, phase, kind, optional = "P7BIS", "3 · Couleurs et export", "creatif", True
    title = "Couleur des étoiles"
    help = ("Retire l'excès de vert des étoiles, puis renforce leur couleur. 1.8 est le réglage que tu as déjà retenu ; "
            "vers 3.0, les étoiles deviennent rouge vif et bruitées. Les étoiles les plus brillantes sont ménagées.")
    params = [P("K", "Renfort K", "float", 1.8, 1.0, 3.0, 0.1), P("vert", "Neutraliser le vert d'abord", "bool", True)]
    default_variants = [{"K": 1.4}, {"K": 1.8}, {"K": 2.5}]
    preview_key = "stars_couleur"
    linear = False
    canonical = {"stars_couleur": "{T}_stars_couleur.fit"}
    produces = ("stars_couleur",)

    def applies(self, p):
        sl, st = layers(p)
        return (st is not None or p.state["steps"].get("P7", {}).get("status") not in ("done", "stale"),
                "pas de calque d'étoiles")

    def ready(self, p):
        return (layers(p)[1] is not None, "valider d'abord les étoiles (P7)")

    def compose_preview(self, ctx, outputs, tag=""):
        g, h = fitsio.read(galaxy_layer(ctx.p))
        s, _ = fitsio.read(ctx.p.abs(outputs["stars_couleur"]))
        out = ctx.out(tag, "apercu")
        fitsio.write(out, fitsio.screen(g, s), h)
        return out

    def run(self, ctx, prm, tag):
        src = layers(ctx.p)[1]
        info = []
        if prm["vert"]:
            n = ctx.out(tag, "stars_neutre")
            txt = ctx.py("neutralise_vert_etoiles.py", [src, n])
            info += [l for l in txt.splitlines() if l.strip()]
            src = n
        d, h = fitsio.read(src)
        R, G, B = d[0], d[1], d[2]
        L = (R + G + B) / 3
        K = prm["K"]
        gain = 1 + (K - 1) * (1 - np.clip((L - 0.6) / 0.35, 0, 1))
        out = np.stack([np.clip(L + gain * (c - L), 0, 1) for c in (R, G, B)])
        o = ctx.out(tag, "stars_couleur")
        fitsio.write(o, out, h)
        return {"outputs": {"stars_couleur": ctx.rel(o)}, "info": info}

    def notes(self, p, st):
        x = st["params"]
        return "Couleur des étoiles : " + ("vert neutralisé, " if x.get("vert") else "") + f"renfort K {x.get('K')}"


class Couleurs(Step):
    id, phase, kind = "P8", "3 · Couleurs et export", "creatif"
    title = "Couleurs du calque sans étoiles"
    help = ("Couleurs de la nébuleuse ou de la galaxie, sur l'image sans étoiles. Au choix : saturation simple (agit "
            "surtout sur un noyau de galaxie), coloration de toute la galaxie, doré / lave, bleu froid, teintes prêtes "
            "(rose-magenta, rouge Hα, émeraude), un dégradé de deux couleurs que tu choisis (zones faibles -> zones "
            "lumineuses), les palettes HOO et cuivre-bleu tirées du filtre LP (Hα = rouge, OIII = vert+bleu), ou les "
            "régions HII du LP (mode B, galaxie). Le réglage fin (température, teinte, saturation…) se fait ensuite, en "
            "direct, à l'étape P8F. En option : aplanir un fond irrégulier (pas sur une nébuleuse qui remplit le champ ; "
            "dessine une zone de contrôle sur une partie faible pour vérifier qu'elle n'est pas effacée) et contraste "
            "local. Chaque aperçu inclut les étoiles ; la colonne « Réf. » montre l'image naturelle.")
    params = [
        P("methode", "Couleur", "choice", "satu",
          choices=[["aucune", "Aucune (naturelle)"], ["satu", "Saturation (satu)"], ["objet", "Galaxie « objet entier »"],
                   ["dore", "Doré / lave"], ["froid", "Bleu froid"], ["rose", "Rose / magenta"], ["rouge", "Rouge Hα"],
                   ["emeraude", "Émeraude / turquoise"], ["degrade", "Dégradé : deux couleurs au choix"],
                   ["hoo", "Palette HOO (filtre LP)"], ["cuivre_bleu", "Palette cuivre-bleu (filtre LP)"],
                   ["hii", "Régions HII du LP (mode B galaxie)"]]),
        P("c1", "Couleur des zones faibles", "color", "#3a5fd0", show_if={"methode": ["degrade"]}),
        P("c2", "Couleur des zones lumineuses", "color", "#ffb070", show_if={"methode": ["degrade"]}),
        P("satu", "Saturation", "float", 0.3, 0, 1, 0.05, show_if={"methode": ["satu"]}),
        P("force", "Force", "float", 0.5, 0.1, 1.5, 0.05,
          show_if={"methode": ["objet", "dore", "froid", "hii", "rose", "rouge", "emeraude", "degrade", "hoo", "cuivre_bleu"]},
          help="objet 0.5/0.8/1.2 · doré 0.25–0.5 · froid 0.35–0.6 · teintes et dégradé 0.3–0.7 · HOO / cuivre-bleu 0.5–1 (1 = palette pure) · HII 0.5/1.0/1.5"),
        P("lissage", "Lissage couleur (px)", "float", 6, 1, 15, 1, show_if={"methode": ["objet", "dore", "froid"]}),
        P("seuil", "Seuil HII (sigma)", "float", 2.5, 1, 6, 0.5, show_if={"methode": ["hii"]}),
        P("aplanir", "Aplanir le fond d'abord", "bool", False),
        P("part_ciel", "Part de ciel", "float", 0.85, 0.5, 0.95, 0.05, show_if={"aplanir": [True]}),
        P("sigma", "Sigma (px)", "float", 40, 10, 120, 5, show_if={"aplanir": [True]}),
        P("zone", "Zone de contrôle x,y,l,h", "text", "", show_if={"aplanir": [True]}, help="bras externe faible (affiché)"),
        P("contraste", "Contraste local ensuite", "bool", False),
        P("c_force", "Force du contraste", "float", 0.6, 0.1, 1.2, 0.05, show_if={"contraste": [True]}),
        P("rayons", "Rayons", "text", "6,20,60", show_if={"contraste": [True]}),
    ]
    default_variants = [{"methode": "satu", "satu": 0.15}, {"methode": "satu", "satu": 0.3}, {"methode": "dore", "force": 0.3}]
    preview_key = "G_final"
    linear = False
    reference_step = "P7T"
    canonical = {"G_final": "{T}_G_final.fit"}

    def ready(self, p):
        return (p.file("naturel") is not None, "valider d'abord l'image naturelle (P7T)")

    def compose_preview(self, ctx, outputs, tag=""):
        return fused_preview(ctx, ctx.p.abs(outputs["G_final"]), tag)

    def run(self, ctx, prm, tag):
        p = ctx.p
        cur = galaxy_layer(p)
        info = []
        if prm["aplanir"]:
            o = ctx.out(tag, "plat")
            args = [cur, o, prm["part_ciel"], int(prm["sigma"]), 1]
            if prm["zone"].strip():
                args += [int(float(v)) for v in prm["zone"].split(",")[:4]]
            txt = ctx.py("aplanir_fond_ciel.py", args)
            info += [l for l in txt.splitlines() if "%" in l or "conserv" in l][-3:]
            cur = o
        m = prm["methode"]
        o = ctx.out(tag, "G")
        if m == "aucune":
            d, h = fitsio.read(cur)
            fitsio.write(o, d, h)
        elif m == "satu":
            tool(ctx, cur, o, [f"satu {prm['satu']}"], "satu")
        elif m == "objet":
            txt = ctx.py("coloration_galaxie.py", [cur, o, prm["force"], prm["lissage"]])
            info += txt.strip().splitlines()[-2:]
        elif m in ("dore", "froid"):
            txt = ctx.py("palette_doree_froide.py", [cur, o, m, prm["force"], prm["lissage"]])
            info += txt.strip().splitlines()[-3:]
        elif m in GRADIENTS or m == "degrade":
            d, h = fitsio.read(cur)
            c1, c2 = (prm["c1"], prm["c2"]) if m == "degrade" else GRADIENTS[m]
            fitsio.write(o, color_ops.gradient(d, c1, c2, prm["force"]), h)
            info.append(f"Dégradé {c1} (zones faibles) -> {c2} (zones lumineuses), force {prm['force']} ; ciel non touché")
        elif m in ("hoo", "cuivre_bleu"):
            info += self.narrowband(ctx, cur, o, m, prm["force"], tag)
        elif m == "hii":
            lp = p.file("lp_starless")
            if not lp:
                raise ValueError("pas de calque LP (piste secondaire du mode B galaxie)")
            txt = ctx.py("combiner_filtres.py", [cur, lp, o, prm["force"], prm["seuil"]])
            info += txt.strip().splitlines()[-4:]
        cur = o
        if prm["contraste"]:
            o2 = ctx.out(tag, "G_contraste")
            txt = ctx.py("contraste_local.py", [cur, o2, prm["c_force"], prm["rayons"]])
            info += txt.strip().splitlines()[-2:]
            cur = o2
        d, _ = fitsio.read(cur)
        s = fitsio.stats(d)
        info.append(f"Médianes R/V/B : {s['medianes']} · écrêtés {s['ecretes_pct']} %")
        info += checks.noise_change(galaxy_layer(p), cur, "après couleurs")
        info = [l for l in info if not (l.startswith("OK") and ("/" in l or "\\" in l))]   # « OK <chemin> » des scripts
        return {"outputs": {"G_final": ctx.rel(cur)}, "info": info}

    def narrowband(self, ctx, cur, o, m, force, tag):
        """HOO / cuivre-bleu à partir du calque sans étoiles : Hα = rouge, OIII = moyenne vert+bleu (filtre LP double bande)."""
        p = ctx.p
        d, h = fitsio.read(cur)
        ha, oiii = ctx.out(tag, "ha"), ctx.out(tag, "oiii")
        fitsio.write(ha, d[0][None], h)
        fitsio.write(oiii, ((d[1] + d[2]) / 2)[None], h)
        pal = ctx.out(tag, m)
        txt = ctx.py("palette_narrowband.py", [m, ha, oiii, pal])
        info = [l for l in txt.strip().splitlines() if not l.startswith("OK")][-1:]
        x, _ = fitsio.read(pal)
        k = float(np.clip(force, 0, 1))
        fitsio.write(o, d * (1 - k) + x * k, h)
        info.append(f"Palette {m} appliquée à {round(k * 100)} % (Hα = rouge, OIII = moyenne vert + bleu)")
        filtres = {str(s.get("filter", "")).upper() for s in p.state.get("sessions", [])}
        if filtres and filtres != {"LP"}:
            info.append("INFO : des poses sans filtre LP (" + ", ".join(sorted(filtres - {"LP"})) + ") sont dans le stack : "
                        "le rouge et le vert/bleu n'y séparent pas Hα et OIII, la palette sera moins marquée.")
        return info

    def notes(self, p, st):
        prm = st.get("params", {})
        m = prm.get("methode")
        d = {"aucune": "aucune", "satu": f"satu {prm.get('satu')}", "objet": f"objet entier {prm.get('force')}",
             "dore": f"doré/lave {prm.get('force')}", "froid": f"bleu froid {prm.get('force')}",
             "rose": f"rose/magenta {prm.get('force')}", "rouge": f"rouge Hα {prm.get('force')}",
             "emeraude": f"émeraude {prm.get('force')}",
             "degrade": f"dégradé {prm.get('c1')} -> {prm.get('c2')} {prm.get('force')}",
             "hoo": f"palette HOO {prm.get('force')}", "cuivre_bleu": f"palette cuivre-bleu {prm.get('force')}",
             "hii": f"régions HII du LP {prm.get('force')}"}.get(m, m)
        s = f"Couleurs : {d}"
        if prm.get("aplanir"):
            s += f" ; aplanissement part_ciel {prm.get('part_ciel')} sigma {prm.get('sigma')}"
        if prm.get("contraste"):
            s += f" ; contraste local {prm.get('c_force')} ({prm.get('rayons')})"
        return s


STEPS = [CouleurEtoiles(), Couleurs()]
