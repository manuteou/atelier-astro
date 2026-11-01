"""Cadre commun des étapes : paramètres, variantes, aperçus."""
import string
from pathlib import Path

from .. import fitsio
from ..siril import Siril, run_py


class P:
    """Paramètre d'étape affiché dans l'interface."""

    def __init__(self, name, label, type="float", default=None, min=None, max=None, step=None,
                 choices=None, help="", show_if=None):
        self.__dict__.update(name=name, label=label, type=type, default=default, min=min, max=max,
                             step=step, choices=choices, help=help, show_if=show_if)

    def as_dict(self):
        return dict(self.__dict__)

    def coerce(self, v):
        if v is None or v == "":
            return self.default
        t = self.type
        if t == "float":
            return float(v)
        if t == "int":
            return int(float(v))
        if t == "bool":
            return v in (True, "true", "1", 1, "on")
        if t in ("rect",):
            return [int(float(a)) for a in v] if v else None
        return v


class Step:
    id = ""
    phase = ""
    title = ""
    help = ""
    kind = "technique"            # technique | creatif | auto | formulaire
    params = []
    default_variants = [{}]
    optional = False
    single = False                # un seul jeu de réglages (étapes lourdes qui réécrivent les mêmes fichiers)
    canonical = {}                # clé de sortie -> nom définitif ("{T}_crop.fit")
    preview_key = None            # sortie montrée en aperçu
    linear = True                 # l'aperçu doit être étiré (image linéaire)
    interaction = None            # "crop" | "point" | "zone" : clic sur l'aperçu
    produces = ()                 # clés retirées si l'étape est passée

    def applies(self, p):
        return True, ""

    def ready(self, p):
        return True, ""

    def defaults(self):
        return {x.name: x.default for x in self.params}

    def clean(self, params):
        out = self.defaults()
        for x in self.params:
            if x.name in (params or {}):
                out[x.name] = x.coerce(params[x.name])
        return out

    def run(self, ctx, prm, tag):
        raise NotImplementedError

    def compose_preview(self, ctx, outputs, tag=""):
        """Fichier à montrer pour une variante (par défaut la sortie preview_key)."""
        return ctx.p.abs(outputs[self.preview_key]) if self.preview_key in outputs else None

    def visible(self, prm):
        out = {}
        for x in self.params:
            if x.show_if and not all(prm.get(k) in vals for k, vals in x.show_if.items()):
                continue
            v = prm.get(x.name)
            if v not in (None, "", []):
                out[x.name] = v
        return out

    def notes(self, p, st):
        prm = self.visible(st.get("params") or {})
        if not prm:
            return f"{self.title} : validé"
        return f"{self.title} : " + ", ".join(f"{k}={str(v).replace(chr(10), ' ; ')}" for k, v in prm.items())

    def meta(self, p):
        ok, why = self.applies(p)
        rd, msg = self.ready(p) if ok else (False, why)
        return {"id": self.id, "phase": self.phase, "title": self.title, "help": self.help, "kind": self.kind,
                "params": [x.as_dict() for x in self.params], "default_variants": self.default_variants,
                "optional": self.optional, "single": self.single or self.kind == "formulaire", "interaction": self.interaction, "applies": ok, "why": why,
                "ready": rd, "ready_msg": msg}


class Ctx:
    """Contexte d'exécution d'une étape."""

    def __init__(self, p, cfg, job, sid, run):
        self.p, self.cfg, self.job, self.sid, self.run_no = p, cfg, job, sid, run
        self.siril = Siril(cfg)

    def log(self, line):
        self.job.write(line)

    def out(self, tag, key, ext=".fit", folder="essais"):
        d = self.p.root / folder
        d.mkdir(exist_ok=True)
        return d / f"{self.p.T}_{self.sid}_r{self.run_no}{tag}_{key}{ext}"

    def sir(self, cmds, cwd=None, name=None):
        return self.siril.run(cmds, cwd or self.p.root, self.log, name or self.sid)

    def py(self, script, args, cwd=None, check=True):
        return run_py(script, args, cwd or self.p.root, self.log, check=check)

    def rel(self, path):
        return self.p.rel(path)


LETTERS = string.ascii_uppercase


def make_previews(ctx, step, var, idx):
    """Aperçu complet + zoom pour une variante (aucun `save` : l'aperçu ne touche pas aux FITS)."""
    p = ctx.p
    try:
        src = step.compose_preview(ctx, var["outputs"], LETTERS[idx])
    except Exception as e:  # noqa
        var.setdefault("info", []).append(f"aperçu impossible : {e}")
        return
    if src is None or not Path(src).exists():
        return
    linear = var.get("linear", step.linear)
    base = p.root / "apercus" / f"{p.T}_{step.id}_r{ctx.run_no}{LETTERS[idx]}"
    meta = fitsio.preview(src, f"{base}.jpg", linear, width=ctx.cfg.get("preview_width", 1200))
    var["previews"] = {"main": p.rel(f"{base}.jpg"), "size": [meta["w"], meta["h"]], "scale": meta["scale"],
                       "source": p.rel(src), "linear": linear}
    if p.state.get("zoom"):
        fitsio.preview(src, f"{base}_zoom.jpg", linear, zoom=p.state["zoom"])
        var["previews"]["zoom"] = p.rel(f"{base}_zoom.jpg")
    try:
        data, _ = fitsio.read(src)
        if linear:
            var["stats"] = fitsio.stats(data)
        else:
            var["stats"] = fitsio.stats(data)
    except Exception:
        pass


def refresh_zoom(p, step_state):
    """Regénère les zooms de toutes les variantes d'une étape après changement de zone."""
    if not p.state.get("zoom"):
        return
    for var in step_state.get("variants", []):
        pv = var.get("previews")
        if not pv or not pv.get("source"):
            continue
        src = p.abs(pv["source"])
        if not src.exists():
            continue
        z = pv["main"].replace(".jpg", "_zoom.jpg")
        fitsio.preview(src, p.abs(z), pv.get("linear", True), zoom=p.state["zoom"])
        pv["zoom"] = z
