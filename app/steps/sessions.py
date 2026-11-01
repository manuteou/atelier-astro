"""Sessions d'un projet : choix des filtres (modes A/B/C), appareils, tableau des poses. Utilisé par toutes les étapes."""
from pathlib import Path

from .. import inventory


def _sessions_for_mode(p):
    """Sessions retenues, LP d'abord puis IRCUT (mode B : plages d'index continues)."""
    ses = p.state.get("sessions", [])
    mode = p.mode
    if mode == "C":
        f = p.state.get("filtre_c", "IRCUT")
        ses = [s for s in ses if s.get("filter") == f]
    order = {"LP": 0, "IRCUT": 1}
    return sorted(ses, key=lambda s: (order.get(s.get("filter"), 2), s.get("name", "")))


def hm(sec):
    sec = float(sec or 0)
    h, m = int(sec // 3600), int(round((sec % 3600) / 60))
    if m == 60:
        h, m = h + 1, 0
    return f"{h} h {m:02d}" if h else f"{m} min"


def pose_table(sessions, models):
    """« S50 Pro : LP 309 poses (51 min) · IRCUT 121 poses (20 min) — total 430 poses (1 h 12) »."""
    tab, names = {}, {}
    for s in sessions:
        d = s.get("device") or "?"
        f = s.get("filter") or "?"
        names.setdefault((d, f), set()).add(s.get("filter_name") or ("sans filtre" if "filter_name" in s else f))
        n = int(s.get("count") or 0)
        t = n * float(s.get("exptime") or 0)
        e = tab.setdefault(d, {}).setdefault(f, [0, 0.0])
        e[0] += n
        e[1] += t
    lines = ["Poses disponibles :"]
    order = {"LP": 0, "IRCUT": 1}
    for d in sorted(tab, key=lambda x: (x != "S50", str(models.get(x, x)))):
        lab = lambda f: (next(iter(names[(d, f)])) if len(names[(d, f)]) == 1 else f) + \
            ("" if f in next(iter(names[(d, f)])) else (" (bi-bande)" if f == "LP" else " (large bande)"))
        parts = [f"{lab(f)} {n} poses ({hm(t)})" for f, (n, t) in sorted(tab[d].items(), key=lambda kv: order.get(kv[0], 2))]
        nt = sum(v[0] for v in tab[d].values())
        tt = sum(v[1] for v in tab[d].values())
        lines.append(f"  {models.get(d, d)} : " + " · ".join(parts) + (f" — total {nt} poses ({hm(tt)})" if len(parts) > 1 else ""))
    return lines


def mode_effect(sessions, models, prm, ttype):
    """Ce que donne le mode choisi avec ces poses-là, appareil par appareil."""
    per = {}
    for x in sessions:
        e = per.setdefault(x.get("device") or "?", {}).setdefault(x.get("filter"), [0, 0.0])
        e[0] += int(x.get("count") or 0)
        e[1] += int(x.get("count") or 0) * float(x.get("exptime") or 0)
    multi = len(per) > 1
    out = []
    for d in sorted(per, key=lambda k: (k != "S50", str(models.get(k, k)))):
        filt = per[d]
        pre = f"{models.get(d, d)} — " if multi else ""
        if not ({"LP", "IRCUT"} <= set(filt)):
            f, (n, t) = next(iter(filt.items()))
            if prm.get("mode") == "C" and f != prm.get("filtre_c"):
                out.append(f"{pre}C ({prm.get('filtre_c')}) : ses {n} poses {f} ({hm(t)}) seront laissées de côté.")
            else:
                out.append(f"{pre}un seul filtre ({f}) : un stack de {n} poses ({hm(t)}).")
            continue
        lp, ir = filt["LP"], filt["IRCUT"]
        m = prm.get("mode")
        if m == "A":
            out.append(f"{pre}avec A : un seul stack de {lp[0] + ir[0]} poses ({hm(lp[1] + ir[1])}).")
            if ttype == "galaxie":
                out.append("  Sur une galaxie, les poses LP apportent très peu : C (IRCUT) est généralement préférable.")
        elif m == "B":
            main, sec = (("LP", lp), ("IRCUT", ir)) if ttype == "nebuleuse" else (("IRCUT", ir), ("LP", lp))
            out.append(f"{pre}avec B : stack principal {main[0]} de {main[1][0]} poses ({hm(main[1][1])}), "
                       f"stack secondaire {sec[0]} de {sec[1][0]} poses ({hm(sec[1][1])}).")
            if ttype == "nebuleuse" and ir[1] < 1800:
                out.append(f"  ATTENTION : seulement {hm(ir[1])} d'IRCUT ; une trentaine de minutes est conseillée pour des étoiles propres.")
        else:
            k = prm.get("filtre_c", "IRCUT")
            kept, left = (lp, ir) if k == "LP" else (ir, lp)
            out.append(f"{pre}avec C ({k}) : {kept[0]} poses ({hm(kept[1])}) gardées, {left[0]} poses ({hm(left[1])}) laissées de côté.")
    return out


def devices(p):
    """Appareils présents (après le choix de filtre), appareil principal en premier."""
    fams = []
    for s in _sessions_for_mode(p):
        d = s.get("device") or inventory.device_family(s.get("instrument"), s.get("focal"))
        if d not in fams:
            fams.append(d)
    pr = p.state.get("principal")
    if pr in fams:
        fams.remove(pr)
        fams.insert(0, pr)
    return fams


def is_multi(p):
    return len(devices(p)) > 1


def groups(p):
    """[(appareil, sessions)] dans l'ordre : principal d'abord."""
    ses = _sessions_for_mode(p)
    out = []
    for d in devices(p):
        out.append((d, [s for s in ses if (s.get("device") or inventory.device_family(s.get("instrument"), s.get("focal"))) == d]))
    return out


def proc_dir(p, dev):
    return p.root / ("process" if not is_multi(p) else f"process_{dev}")


def model(p, dev):
    """Nom affiché d'un appareil (fiche Matériel)."""
    from .. import materiel
    return materiel.name(p, dev)


def _find(root, stem):
    for ext in (".fit", ".fits", ".fts"):
        f = Path(root) / f"{stem}{ext}"
        if f.exists():
            return f
    return None
