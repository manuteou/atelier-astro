"""Qualité du ciel mesurée sur les poses brutes, en mag/arcsec² (l'unité des SQM), puis classe de Bortle approximative.

Principe (photométrie différentielle, rien à régler) :
  1. pose brute IRCUT moins le piédestal du capteur (mot-clé BIAS écrit par le Seestar), superpixels 2x2 ;
  2. étoiles du catalogue Gaia (Internet, mis en cache dans le projet) projetées autour du centre RA/DEC de l'en-tête,
     appariées aux étoiles détectées (triangles semblables, échelle connue par la focale) ;
  3. photométrie d'ouverture des étoiles isolées : point zéro = magnitude V (Gaia G et BP-RP convertis) moins
     magnitude instrumentale ; il calibre le flux du fond de ciel, d'où sa brillance surfacique ;
  4. correction vers le zénith (hauteur de la cible) : m_zénith ≈ m + 2,5 log10(X) + k, k = 0,2 (extinction).
Les poses voilées (point zéro effondré : nuages, buée), basses (< 25°) ou prises au crépuscule sont écartées ; la Lune
levée est signalée. Précision réaliste : ± 0,3 mag/arcsec². Les poses LP (filtre bi-bande) ne sont pas comparables à
un SQM : seules les sessions IRCUT (ou sans filtre) sont mesurées."""
import csv
import io
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from astropy.io import fits
from scipy.spatial import cKDTree

from . import align
from .sites import bortle_de_sqm

VERSION = 1
K_EXT = 0.2                  # extinction typique en V (mag par masse d'air)
HAUTEUR_MIN = 25.0
POSES_PAR_SESSION = 8
TAP = (("https://gea.esac.esa.int/tap-server/tap/sync", 75), ("https://gaia.ari.uni-heidelberg.de/tap/sync", 40))
APR, ANN = 6, 10             # rayon d'ouverture et début de l'anneau de fond, en superpixels


def mesurable(session):
    return "LP" not in str(session.get("filter") or "").upper()


# ---------------------------------------------------------------- catalogue

def catalogue(ra, dec, rayon, cache_dir=None, mag_max=12.8):
    """Étoiles Gaia DR3 (ra, dec, g, bp_rp) dans un cône. Cache JSON par champ ; ATELIER_CATALOGUE (fichier JSON au
    même format) remplace la requête (tests, usage hors ligne)."""
    f = os.environ.get("ATELIER_CATALOGUE")
    if f:
        return _tableau(json.loads(Path(f).read_text(encoding="utf-8")))
    cache = None
    if cache_dir:
        cache = Path(cache_dir) / f"gaia_{ra:.2f}_{dec:+.2f}_{rayon:.2f}_{mag_max:.1f}.json"
        if cache.exists():
            return _tableau(json.loads(cache.read_text(encoding="utf-8")))
    q = ("SELECT ra, dec, phot_g_mean_mag AS g, bp_rp FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS',ra,dec),"
         f"CIRCLE('ICRS',{ra:.5f},{dec:.5f},{rayon:.3f})) AND phot_g_mean_mag < {mag_max}")
    data = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": q}).encode()
    err = None
    for url, delai in TAP:
        try:
            txt = urllib.request.urlopen(url, data, timeout=delai).read().decode("utf-8")
            rows = [{k: r[k] for k in ("ra", "dec", "g", "bp_rp")} for r in csv.DictReader(io.StringIO(txt))]
            if rows:
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(rows), encoding="utf-8")
                return _tableau(rows)
        except Exception as e:                       # serveur lent ou injoignable : on essaie le miroir
            err = e
    raise ValueError(f"catalogue Gaia injoignable ({err or 'réponse vide'})")


def _tableau(rows):
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return np.nan
    a = np.array([[num(r.get("ra")), num(r.get("dec")), num(r.get("g")), num(r.get("bp_rp"))] for r in rows], float)
    return a.reshape(-1, 4)


def v_de_gaia(g, bp_rp):
    """Magnitude V de Johnson à partir de G et BP-RP (Riello et al. 2021)."""
    c = bp_rp
    return g + 0.02704 - 0.01424 * c + 0.2156 * c ** 2 - 0.01426 * c ** 3


# ---------------------------------------------------------------- géométrie du ciel

def _jd(t):
    return t.timestamp() / 86400.0 + 2440587.5


def _gmst_deg(jd):
    d = jd - 2451545.0
    return (280.46061837 + 360.98564736629 * d) % 360


def _hauteur(ra, dec, lat, lon, jd):
    ha = math.radians((_gmst_deg(jd) + lon - ra) % 360)
    la, de = math.radians(lat), math.radians(dec)
    s = math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(ha)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def _soleil(jd):
    """RA, Dec apparentes du Soleil (précision ~0,1°, largement suffisante ici)."""
    n = jd - 2451545.0
    L = math.radians((280.460 + 0.9856474 * n) % 360)
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    eps = math.radians(23.439 - 4e-7 * n)
    return math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360, \
        math.degrees(math.asin(math.sin(eps) * math.sin(lam)))


def _lune(jd):
    """RA, Dec géocentriques de la Lune (termes principaux, ~0,5°)."""
    T = (jd - 2451545.0) / 36525
    r = math.radians
    Lp = r(218.316 + 481267.881 * T)
    M = r(134.963 + 477198.867 * T)
    Ms = r(357.529 + 35999.050 * T)
    D = r(297.850 + 445267.111 * T)
    F = r(93.272 + 483202.018 * T)
    lam = Lp + r(6.289) * math.sin(M) + r(1.274) * math.sin(2 * D - M) + r(0.658) * math.sin(2 * D) \
        + r(0.214) * math.sin(2 * M) - r(0.186) * math.sin(Ms) - r(0.114) * math.sin(2 * F)
    bet = r(5.128) * math.sin(F) + r(0.281) * math.sin(M + F) + r(0.278) * math.sin(M - F) + r(0.173) * math.sin(2 * D - F)
    eps = r(23.439)
    ra = math.atan2(math.sin(lam) * math.cos(eps) - math.tan(bet) * math.sin(eps), math.cos(lam))
    dec = math.asin(math.sin(bet) * math.cos(eps) + math.cos(bet) * math.sin(eps) * math.sin(lam))
    return math.degrees(ra) % 360, math.degrees(dec)


def _date(h):
    s = str(h.get("DATE-OBS") or "").strip()
    if not s:
        raise ValueError("pas de date (DATE-OBS) dans l'en-tête")
    t = datetime.fromisoformat(s.replace("Z", ""))
    exp = float(h.get("EXPTIME") or h.get("EXPOSURE") or 0)
    from datetime import timedelta
    return (t + timedelta(seconds=exp / 2)).replace(tzinfo=timezone.utc)


def _coord(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(":", " ").split()
    sg = -1 if s and s[0].startswith("-") else 1
    parts = [abs(float(x)) for x in s]
    return sg * (parts[0] + (parts[1] if len(parts) > 1 else 0) / 60 + (parts[2] if len(parts) > 2 else 0) / 3600)


def _tangente(ra, dec, ra0, dec0):
    a, d, d0 = np.radians(ra - ra0), np.radians(dec), math.radians(dec0)
    c = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(a)
    xi = np.cos(d) * np.sin(a) / c
    eta = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(a)) / c
    return np.degrees(xi) * 3600, np.degrees(eta) * 3600


# ---------------------------------------------------------------- mesure d'une pose

def entete(path):
    with fits.open(path, memmap=False) as hd:
        return hd[0].header


def champ(h):
    """(ra, dec, rayon du cône en degrés) d'une pose, d'après RA/DEC, focale et taille du capteur."""
    ra, dec = float(h["RA"]), float(h["DEC"])
    f, pix = float(h["FOCALLEN"]), float(h["XPIXSZ"])
    w, hh = int(h.get("NAXIS1") or 0), int(h.get("NAXIS2") or 0)
    diag = math.hypot(w, hh) * 206.265 * pix / f / 3600
    return ra, dec, max(0.3, min(2.0, diag / 2 * 1.05))


def mesure_pose(path, cat):
    """Dictionnaire de la mesure d'une pose brute (ValueError si impossible)."""
    with fits.open(path, memmap=False) as hd:
        h, raw = hd[0].header, hd[0].data
    if raw is None:
        raise ValueError("pose vide")
    if "BIAS" not in h:
        raise ValueError("pas de piédestal du capteur (BIAS) dans l'en-tête : brillance du ciel impossible à isoler")
    for k in ("RA", "DEC", "FOCALLEN", "XPIXSZ", "EXPTIME"):
        if h.get(k) in (None, ""):
            raise ValueError(f"en-tête incomplet ({k})")
    t = float(h["EXPTIME"])
    raw = raw.astype(np.float64)
    sat = 0.9 * float(np.nanmax(raw))                # le blanc du capteur (étoiles saturées écartées)
    d = raw - float(h["BIAS"])
    if d.ndim == 3:                                  # pose déjà dématricée (R, V, B)
        L, k = d.sum(0), 1
        satmap = raw.max(0)
    else:
        H2, W2 = d.shape[0] // 2 * 2, d.shape[1] // 2 * 2
        d, raw = d[:H2, :W2], raw[:H2, :W2]
        L = d[0::2, 0::2] + d[0::2, 1::2] + d[1::2, 0::2] + d[1::2, 1::2]
        satmap = np.maximum.reduce([raw[0::2, 0::2], raw[0::2, 1::2], raw[1::2, 0::2], raw[1::2, 1::2]])
        k = 2
    echelle = k * 206.265 * float(h["XPIXSZ"]) / float(h["FOCALLEN"])         # arcsec par (super)pixel
    H, W = L.shape
    ra0, dec0 = float(h["RA"]), float(h["DEC"])
    ok = np.isfinite(cat).all(1)
    c = cat[ok]
    xi, eta = _tangente(c[:, 0], c[:, 1], ra0, dec0)
    gx, gy = xi / echelle, eta / echelle
    xy, _ = align.detect(L, 400)
    if len(xy) < 12:
        raise ValueError(f"trop peu d'étoiles détectées ({len(xy)})")
    vis = np.hypot(gx, gy) < 0.5 * math.hypot(W, H)  # dans le champ quelle que soit l'orientation
    ordre = np.nonzero(vis)[0][np.argsort(c[vis, 2])]
    best = None
    for ns in (60, 100, 150, 40):
        src = np.c_[gx, gy][ordre[:ns]]
        for mir in (False, True):
            res = align._match(src, xy[:ns + 40], mirror=mir, scale=1.0)
            if res and (best is None or res[2] > best[0][2]):
                best = (res, mir)
        if best and best[0][2] >= 25:
            break
    if best is None or best[0][2] < 8:
        raise ValueError("étoiles du catalogue non retrouvées sur la pose (centre RA/DEC ou focale faux ?)")
    (A, T, n_app, rms), mir = best
    z = gx + 1j * gy
    z = (np.conj(z) * -1 if mir else z) * A + T
    px, py = z.real, z.imag
    R = ANN + 4
    m = R + 2
    dedans = (px > m) & (px < W - m) & (py > m) & (py < H - m)
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    rr = np.hypot(xx, yy)
    arbre = cKDTree(np.c_[px, py])
    V = v_de_gaia(c[:, 2], c[:, 3])
    pts = []
    for i in np.nonzero(dedans & (c[:, 2] > 8) & (c[:, 2] < 12.8))[0]:
        if any(c[j, 2] < c[i, 2] + 3 for j in arbre.query_ball_point([px[i], py[i]], R) if j != i):
            continue                                 # voisine trop brillante dans l'anneau
        cx, cy = int(round(px[i])), int(round(py[i]))
        cut = L[cy - R:cy + R + 1, cx - R:cx + R + 1]
        if satmap[cy - 2:cy + 3, cx - 2:cx + 3].max() >= sat:
            continue
        b = np.median(cut[rr >= ANN])
        fl = float((cut[rr <= APR] - b).sum())
        if fl > 0:
            pts.append(V[i] + 2.5 * math.log10(fl / t))
    if len(pts) < 10:
        raise ValueError(f"trop peu d'étoiles mesurables ({len(pts)})")
    zp = np.array(pts)
    med = float(np.median(zp))
    for _ in range(3):
        sig = 1.4826 * float(np.median(np.abs(zp - med))) or 0.01
        garde = np.abs(zp - med) < 3 * sig
        med = float(np.median(zp[garde]))
    fond = float(np.median(align._fond_local(L, 8, 15)))
    if fond <= 0:
        raise ValueError("fond de ciel nul ou négatif après retrait du piédestal")
    m_ciel = med - 2.5 * math.log10(fond / t / echelle ** 2)
    out = {"fichier": Path(path).name, "zp": round(med, 3), "zp_sigma": round(sig, 3), "etoiles": int(garde.sum()),
           "ciel": round(m_ciel, 2), "echelle": round(echelle, 3)}
    try:
        tu = _date(h)
        jd = _jd(tu)
        lat, lon = _coord(h["SITELAT"]), _coord(h["SITELONG"])
        alt = _hauteur(ra0, dec0, lat, lon, jd)
        out.update(heure=tu.isoformat(), hauteur=round(alt, 1),
                   soleil=round(_hauteur(*_soleil(jd), lat, lon, jd), 1),
                   lune=round(_hauteur(*_lune(jd), lat, lon, jd), 1))
        if alt > 5:
            X = 1 / math.sin(math.radians(alt))
            out["zenith"] = round(m_ciel + 2.5 * math.log10(X) + K_EXT, 2)
    except (KeyError, ValueError, TypeError):
        pass
    return out


# ---------------------------------------------------------------- sessions

def echantillon(fichiers, n=POSES_PAR_SESSION):
    if len(fichiers) <= n:
        return list(fichiers)
    idx = np.linspace(0, len(fichiers) - 1, n).round().astype(int)
    return [fichiers[i] for i in sorted(set(idx))]


def trier(mesures):
    """Ajoute à chaque mesure 'retenue' (bool) et 'motif' (écart), d'après la transparence de la session, la hauteur,
    le crépuscule. Les poses Lune levée restent retenues mais signalées, sauf s'il y en a sans Lune."""
    ok = [m for m in mesures if "zenith" in m]
    zmax = max((m["zp"] for m in ok if m["zp_sigma"] < 0.5), default=None)
    for m in mesures:
        motif = None
        if "zenith" not in m:
            motif = "hauteur ou date inconnue"
        elif m["zp_sigma"] >= 0.5 or (zmax is not None and m["zp"] < zmax - 0.4):
            motif = f"voile (nuages ou buée : {zmax - m['zp']:.1f} mag perdues)" if zmax else "photométrie instable"
        elif m["hauteur"] < HAUTEUR_MIN:
            motif = f"cible trop basse ({m['hauteur']:.0f}°)"
        elif m["soleil"] > -15:
            motif = "crépuscule"
        m["retenue"], m["motif"] = motif is None, motif
    sans_lune = [m for m in mesures if m["retenue"] and m.get("lune", -90) <= 0]
    if sans_lune:
        for m in mesures:
            if m["retenue"] and m.get("lune", -90) > 0:
                m["retenue"], m["motif"] = False, f"Lune levée ({m['lune']:.0f}°)"
    return mesures


def resume(mesures):
    """(valeur au zénith, classe de Bortle, dispersion) des poses retenues, ou None."""
    v = [m["zenith"] for m in mesures if m.get("retenue")]
    if not v:
        return None
    med = float(np.median(v))
    return {"sqm": round(med, 2), "bortle": bortle_de_sqm(med), "min": round(min(v), 2), "max": round(max(v), 2),
            "poses": len(v), "lune": any(m.get("lune", -90) > 0 for m in mesures if m.get("retenue"))}


def mesurer_sessions(sessions, lights_of, cache_dir, log=None):
    """{nom de session: {"mesures": [...], "resume": {...} | None, "erreur": str | None}} pour les sessions mesurables."""
    out = {}
    for s in sessions:
        nom = Path(s["path"]).name
        if not mesurable(s):
            continue
        try:
            fichiers = lights_of(s["path"])
            if not fichiers:
                raise ValueError("aucune pose")
            ra, dec, r = champ(entete(fichiers[0]))
            cat = catalogue(ra, dec, r, cache_dir)
            mes = []
            for f in echantillon(fichiers):
                try:
                    mes.append(mesure_pose(f, cat))
                except ValueError as e:
                    mes.append({"fichier": Path(f).name, "erreur": str(e)})
                if log:
                    log(f"qualité du ciel : {nom} — {Path(f).name}")
            bonnes = trier([m for m in mes if "erreur" not in m])
            out[nom] = {"mesures": mes, "resume": resume(bonnes), "erreur": None if bonnes else
                        "aucune pose mesurable : " + "; ".join(sorted({m["erreur"] for m in mes if "erreur" in m}))}
        except (ValueError, KeyError, OSError) as e:
            out[nom] = {"mesures": [], "resume": None, "erreur": str(e)}
    return out


def graphique(res, out_png):
    """Brillance du ciel (ramenée au zénith) de chaque pose mesurée selon l'heure locale, avec les bandes de Bortle.
    Retourne True si un graphique a été écrit."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    pts = [(nom, m) for nom, r in res.items() for m in r["mesures"] if "zenith" in m and "heure" in m]
    if not pts:
        return False
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=110)
    vals = [m["zenith"] for _, m in pts]
    lo, hi = min(vals + [18.5]) - 0.4, max(vals + [20.0]) + 0.4
    bornes = [(22.5, 21.75, 1), (21.75, 21.6, 2), (21.6, 21.3, 3), (21.3, 20.8, 4), (20.8, 20.3, 5), (20.3, 19.25, 6),
              (19.25, 18.5, 7), (18.5, 18.0, 8), (18.0, 15.0, 9)]
    for haut, bas, b in bornes:
        if bas < hi and haut > lo:
            ax.axhspan(bas, haut, color="#1d2b53" if b % 2 else "#f2b84b", alpha=0.10 if b % 2 else 0.12, lw=0)
            ax.text(1.005, (max(bas, lo) + min(haut, hi)) / 2, f"Bortle {b}", transform=ax.get_yaxis_transform(),
                    fontsize=8, va="center", color="#555")
    couleurs = ["#3fa6ff", "#7c5cff", "#3ccf8e", "#f2b84b", "#ff6b6b"]
    for i, nom in enumerate(res):
        mm = [m for n, m in pts if n == nom]
        if not mm:
            continue
        c = couleurs[i % len(couleurs)]
        hs = [datetime.fromisoformat(m["heure"]).astimezone().replace(tzinfo=None) for m in mm]
        for h, m in zip(hs, mm):
            ax.plot([h], [m["zenith"]], "o", ms=8, color=c, mfc=c if m.get("retenue") else "white", mew=1.6)
            if not m.get("retenue") and m.get("motif"):
                ax.annotate(m["motif"].split(" (")[0], (h, m["zenith"]), textcoords="offset points", xytext=(6, 4),
                            fontsize=7, color="#666")
        ax.plot(hs, [m["zenith"] for m in mm], "-", color=c, lw=1, alpha=0.5, label=nom)
    ax.set_ylim(lo, hi)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_xlabel("heure locale")
    ax.set_ylabel("brillance du ciel au zénith (mag/arcsec²)\n↑ plus noir")
    ax.set_title("Qualité du ciel mesurée sur les poses (points pleins : retenus ; creux : écartés)", fontsize=11)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(out_png, facecolor="white")
    plt.close(fig)
    return True


def lignes(res, bortle_declare=None):
    """Lignes de résumé pour l'étape (et le résumé global retenu : dict ou None)."""
    out, globaux = [], []
    for nom, r in res.items():
        s = r.get("resume")
        if s:
            globaux.append(s)
            plage = f" (de {s['min']:.1f} à {s['max']:.1f})" if s["poses"] > 1 and s["max"] - s["min"] >= 0.1 else ""
            out.append(f"Ciel mesuré, {nom} : {s['sqm']:.1f} mag/arcsec² au zénith{plage}, ≈ Bortle {s['bortle']} "
                       f"({s['poses']} poses retenues" + (", Lune levée" if s["lune"] else "") + ").")
        elif r.get("erreur"):
            out.append(f"Ciel non mesuré, {nom} : {r['erreur']}.")
        voiles = [m for m in r["mesures"] if (m.get("motif") or "").startswith("voile")]
        if voiles:
            heures = ", ".join(datetime.fromisoformat(m["heure"]).astimezone().strftime("%H:%M")
                               for m in voiles if m.get("heure"))
            out.append(f"ATTENTION : {len(voiles)} pose(s) voilée(s) (nuages, buée) sur les {len(r['mesures'])} "
                       f"échantillonnées dans {nom}" + (f", vers {heures}" if heures else "") + ". Un voile assombrit le "
                       "fond au lieu de l'éclaircir : le tri de S2 n'attrape que les voiles qui font perdre la plupart "
                       "des étoiles. Vérifie en S3 que les poses de cette période sont dans la liste à écarter : elles "
                       "ajoutent du bruit sans signal.")
    if not globaux:
        return out, None
    best = max(globaux, key=lambda s: s["poses"])
    if bortle_declare:
        d = best["bortle"] - int(bortle_declare)
        if abs(d) >= 2:
            out.append(f"ATTENTION : la mesure (≈ Bortle {best['bortle']}) s'écarte de la classe indiquée en S1 "
                       f"(Bortle {bortle_declare}) : ciel {'plus clair' if d > 0 else 'plus noir'} que prévu ce soir-là "
                       "(Lune, brume, éclairage), ou classe à revoir pour ce lieu.")
        else:
            out.append(f"La mesure confirme la classe indiquée en S1 (Bortle {bortle_declare}).")
    out.append("  (mesure photométrique sur les étoiles du catalogue Gaia, précision ± 0,3 mag ; repère : 22 = ciel "
               "parfait, 21 = campagne, 19 = banlieue, 17 = ville)")
    return out, best
