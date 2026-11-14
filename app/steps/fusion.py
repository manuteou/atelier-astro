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
            "En mode B (étoiles de l'IRCUT), vérifie sur un zoom qu'aucune étoile n'est doublée ni décalée. Faite et "
            "validée d'elle-même après l'étape précédente ; l'appli ne s'y arrête qu'en cas d'alerte (étoiles doublées…).")
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
    help = ("Dernier débruitage, facultatif, avant l'export : 0.2 / 0.4 / 0.6. Il s'ajoute au débruitage linéaire (P4) "
            "et, le cas échéant, à celui du bicolore : si le grain avait déjà baissé de plus de 60 % en P4, l'appli le "
            "signale et propose des forces plus basses. Si l'image est déjà propre, passe l'étape. Le même réglage est "
            "appliqué à la version naturelle. Outil : Réglages > Outils.")
    params = [P("dn", "Force", "float", 0.4, 0, 1, 0.05)]
    default_variants = [{"dn": 0.2}, {"dn": 0.4}, {"dn": 0.6}]
    SEUIL_DEJA_FORT = -60            # baisse du grain en P4 (en %) au-delà de laquelle un 2e débruitage est risqué
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

    def deja_fort(self, p):
        """Baisse du grain obtenue au débruitage linéaire (P4 validé), si elle dépasse le seuil ; sinon None."""
        st = p.state["steps"].get("P4", {})
        g = p.state["facts"].get("grain_p4_pct")
        return g if st.get("status") == "done" and g is not None and g <= self.SEUIL_DEJA_FORT else None

    def meta(self, p):
        m = super().meta(p)
        if self.deja_fort(p) is not None:
            m["default_variants"] = [{"dn": 0.1}, {"dn": 0.2}, {"dn": 0.35}]
        return m

    def summary(self, p):
        g = self.deja_fort(p)
        if g is None:
            return None
        return [f"Le débruitage linéaire (P4) a déjà baissé le grain de {abs(g)} % : un second débruitage fort donnerait "
                "un rendu lisse, « plastique ». Forces proposées plus basses ; si l'image te paraît propre, passe l'étape."]

    def run(self, ctx, prm, tag):
        from .. import outils
        p = ctx.p
        a, b = ctx.out(tag, "fusion_nxt"), ctx.out(tag, "naturel_nxt")
        cmds = outils.commandes(ctx.cfg, "debruitage", prm["dn"])
        tool(ctx, p.file("fusion"), a, cmds, "debruitage_final")
        tool(ctx, p.file("naturel"), b, cmds, "debruitage_final_naturel")
        info = checks.noise_change(p.file("fusion"), a, "après débruitage final", "baisse")
        g = self.deja_fort(p)
        if g is not None and float(prm["dn"]) > 0.35:
            info.append(f"ATTENTION débruitage cumulé fort : le grain avait déjà baissé de {abs(g)} % en P4 et la force "
                        f"ici est de {prm['dn']}. Compare au zoom avec la référence : si les détails fins de la "
                        "nébuleuse deviennent lisses, prends une force plus basse ou passe l'étape.")
        return {"outputs": {"fusion_nxt": ctx.rel(a), "naturel_nxt": ctx.rel(b)}, "info": info}

    def notes(self, p, st):
        from .. import config, outils
        return (f"Débruitage final : {outils.nom(config.load(), 'debruitage')} {st['params'].get('dn')} "
                "(mêmes réglages sur la version naturelle)")


STEPS = [Fusion(), NXTFinal()]
