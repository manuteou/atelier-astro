"""Phase 3 (3/4) : fusion en écran du calque couleur et des étoiles (P9), débruitage final (P10)."""
from .. import checks, fitsio
from .base import Step, P
from .couleurs import stars_final
from .etoiles import controle_lines
from .lineaire import tool


class Fusion(Step):
    id, phase, kind = "P9", "3 · Couleurs et export", "auto"
    title = "Fusion en écran"
    help = ("Réunit le calque couleur et les étoiles. La colonne « Réf. » montre l'image brute recadrée pour comparer. "
            "En mode B (étoiles de l'IRCUT), vérifie sur un zoom qu'aucune étoile n'est doublée ni décalée.")
    params = []
    preview_key = "fusion"
    linear = False
    reference_step = "P0"
    canonical = {"fusion": "{T}_fusion.fit"}

    def ready(self, p):
        return (p.file("G_final") is not None, "valider d'abord les couleurs (P8)")

    def run(self, ctx, prm, tag):
        p = ctx.p
        gsrc = p.latest("G_fin", "G_final")
        g, h = fitsio.read(gsrc)
        s = stars_final(p)
        out = ctx.out(tag, "fusion")
        info = []
        if s:
            st, _ = fitsio.read(s)
            fitsio.write(out, fitsio.screen(g, st), h)
            txt = ctx.py("controle.py", ["ecran", out, gsrc, s], check=False)
            info += [l.strip() for l in txt.splitlines() if l.startswith(("OK", "ATTENTION"))][:3]
        else:
            fitsio.write(out, g, h)
            info.append("Pas de calque d'étoiles : la fusion est le calque couleur.")
        info += controle_lines(ctx, out, ["--etoiles", s] if s else [])
        if s and p.mode == "B":
            d, _ = fitsio.read(out)
            info += checks.doubled_stars(d)
        return {"outputs": {"fusion": ctx.rel(out)}, "info": info}

    def notes(self, p, st):
        return "Fusion en écran : calque couleur + étoiles"


class NXTFinal(Step):
    id, phase, kind, optional = "P10", "3 · Couleurs et export", "creatif", True
    help = ("Dernier débruitage, facultatif, avant l'export : 0.3 / 0.5 / 0.8. Si le débruitage linéaire était déjà "
            "fort (0.8 ou plus), commence par 0.3. Le même réglage est appliqué à la version naturelle. "
            "Outil : Réglages > Outils.")
    params = [P("dn", "Force", "float", 0.5, 0, 1, 0.05)]
    default_variants = [{"dn": 0.3}, {"dn": 0.5}, {"dn": 0.8}]
    preview_key = "fusion_nxt"
    linear = False
    reference_step = "P9"            # colonne « Réf. » : l'image avant le débruitage final, pour comparer
    canonical = {"fusion_nxt": "{T}_fusion_nxt.fit", "naturel_nxt": "{T}_fusion_naturel_nxt.fit"}
    produces = ("fusion_nxt", "naturel_nxt")

    @property
    def title(self):
        from .. import config, outils
        return f"Débruitage final ({outils.nom(config.load(), 'debruitage')})"

    def applies(self, p):
        from .. import config, outils
        return outils.sans_objet(config.load(), "debruitage")

    def ready(self, p):
        return (p.file("fusion") is not None, "valider d'abord la fusion (P9)")

    def run(self, ctx, prm, tag):
        from .. import outils
        p = ctx.p
        a, b = ctx.out(tag, "fusion_nxt"), ctx.out(tag, "naturel_nxt")
        cmds = outils.commandes(ctx.cfg, "debruitage", prm["dn"])
        tool(ctx, p.file("fusion"), a, cmds, "debruitage_final")
        tool(ctx, p.file("naturel"), b, cmds, "debruitage_final_naturel")
        return {"outputs": {"fusion_nxt": ctx.rel(a), "naturel_nxt": ctx.rel(b)},
                "info": checks.noise_change(p.file("fusion"), a, "après débruitage final", "baisse")}

    def notes(self, p, st):
        from .. import config, outils
        return (f"Débruitage final : {outils.nom(config.load(), 'debruitage')} {st['params'].get('dn')} "
                "(mêmes réglages sur la version naturelle)")


STEPS = [Fusion(), NXTFinal()]
