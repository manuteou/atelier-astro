"""Projet : état (project.json), fichiers validés, invalidation des étapes suivantes."""
import json
import re
import shutil
import threading
import time
from pathlib import Path

LOCK = threading.RLock()


def slug(name):
    import unicodedata
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9_-]+", "", name.replace(" ", ""))
    return s or "Cible"


class Project:
    def __init__(self, root: Path, state: dict):
        self.root = Path(root)
        self.state = state

    # ------------------------------------------------------------ création --
    @classmethod
    def create(cls, astro_root, target, ttype, device, sessions):
        T = slug(target)
        root = Path(astro_root) / f"{T}_combined"
        root.mkdir(parents=True, exist_ok=True)
        for d in ("process", "essais", "apercus", "exports", "fiche", "_scripts"):
            (root / d).mkdir(exist_ok=True)
        if (root / "project.json").exists():
            p = cls.load(root)
            known = {s["path"] for s in p.state.get("sessions", [])}
            added = [s for s in sessions if s["path"] not in known]
            if added:                               # nouvelles nuits pour une cible existante
                p.state["sessions"] += added
                for st in p.state["steps"].values():
                    if st.get("status") == "done":
                        st["status"] = "stale"
                p.save()
            return p
        state = {
            "name": root.name, "target": target, "T": T, "type": ttype,
            "device": device or next((x.get("instrument") for x in sessions if x.get("instrument")), ""),
            "created": time.strftime("%Y-%m-%d %H:%M"), "sessions": sessions, "mode": "unique",
            "zoom": None, "steps": {}, "files": {}, "facts": {}, "fiche": {},
        }
        p = cls(root, state)
        p.save()
        return p

    @classmethod
    def load(cls, root):
        root = Path(root)
        st = json.loads((root / "project.json").read_text(encoding="utf-8"))
        return cls(root, st)

    def save(self):
        with LOCK:
            tmp = self.root / "project.json.tmp"
            tmp.write_text(json.dumps(self.state, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.root / "project.json")

    # ---------------------------------------------------------- raccourcis --
    @property
    def T(self):
        return self.state["T"]

    @property
    def type(self):
        return self.state["type"]

    @property
    def mode(self):
        return self.state.get("mode", "unique")

    def rel(self, path):
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()

    def abs(self, rel):
        return self.root / rel

    def step(self, sid):
        return self.state["steps"].setdefault(sid, {"status": "todo", "runs": 0, "variants": []})

    def file(self, key):
        rel = self.state["files"].get(key)
        if rel and (self.root / rel).exists():
            return self.root / rel
        return None

    def latest(self, *keys):
        for k in keys:
            f = self.file(k)
            if f:
                return f
        return None

    def new_run(self, sid):
        st = self.step(sid)
        st["runs"] = st.get("runs", 0) + 1
        return st["runs"]

    # ---------------------------------------------------------- validation --
    def validate(self, sid, idx, canonical_names, order):
        """Recopie les sorties de la variante choisie sous leurs noms définitifs et invalide la suite."""
        st = self.step(sid)
        var = st["variants"][idx]
        if var.get("error"):
            raise ValueError("cette variante a échoué")
        outs = {}
        for key, rel in var.get("outputs", {}).items():
            src = self.root / rel
            name = canonical_names.get(key)
            if name is None:
                outs[key] = rel
                continue
            dst = self.root / name
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
            outs[key] = self.rel(dst)
        for key, rel in outs.items():
            self.state["files"][key] = rel
        retained = {k: var.get(k) for k in ("params", "previews", "info", "stats", "images", "tag", "run", "pdf")}
        st.update(status="done", chosen=idx, params=var["params"], outputs=outs, info=var.get("info", []), retained=retained,
                  validated_at=time.strftime("%Y-%m-%d %H:%M"))
        self.invalidate_after(sid, order)
        self.save()

    def skip(self, sid, order, keys=()):
        st = self.step(sid)
        st.update(status="skipped", outputs={}, chosen=None)
        for k in keys:
            self.state["files"].pop(k, None)
        self.invalidate_after(sid, order)
        self.save()

    def invalidate_after(self, sid, order):
        if sid not in order:
            return
        for later in order[order.index(sid) + 1:]:
            st = self.state["steps"].get(later)
            if st and st.get("status") == "done":
                st["status"] = "stale"

    def reopen(self, sid):
        st = self.step(sid)
        if st.get("status") in ("done", "stale", "skipped"):
            st["status"] = "todo"
        self.save()


def list_projects(astro_root):
    root = Path(astro_root)
    out = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        pj = d / "project.json"
        if pj.exists():
            try:
                st = json.loads(pj.read_text(encoding="utf-8"))
                done = sum(1 for s in st.get("steps", {}).values() if s.get("status") == "done")
                out.append({"name": d.name, "target": st.get("target"), "type": st.get("type"),
                            "created": st.get("created"), "done": done})
            except Exception:
                pass
    return out
