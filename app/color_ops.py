"""Opérations de couleur sur image étirée (0-1, forme (3, H, W)).

`tune` est le réglage fin de l'étape P8F : la même formule est réécrite en JavaScript (web/js/etapes/reglage_fin.js, liveTune)
pour l'aperçu en direct ; l'application en pleine résolution passe par ici. Toute modification doit être faite
des deux côtés.
"""
import numpy as np


def hex_rgb(h):
    h = str(h).lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def object_weight(L, lo_pc=60, hi_pc=99.5, blur=8):
    import cv2
    ls = cv2.GaussianBlur(L, (0, 0), blur)
    lo, hi = np.percentile(ls, lo_pc), np.percentile(ls, hi_pc)
    w = np.clip((ls - lo) / max(hi - lo, 1e-6), 0, 1)
    return (w * w * (3 - 2 * w)).astype(np.float32), float(hi)


def gradient(x, c1, c2, force=0.5, etendue=1.0, gamma=1.0):
    """Teinte de l'objet par un dégradé de deux couleurs (zones faibles -> zones lumineuses), luminance conservée,
    ciel non touché. `etendue` : 1 = toute la nébuleuse, franges faibles comprises (le dégradé part juste au-dessus
    du ciel) ; 0 = seulement les zones lumineuses (au-dessus du 60e percentile, l'ancien comportement)."""
    import cv2
    from . import fitsio
    L = x.mean(0)
    ls = cv2.GaussianBlur(L, (0, 0), 8)
    mask = fitsio.sky_mask(x)
    sky = float(np.median(ls[mask])) if mask.any() else float(np.percentile(ls, 20))
    bruit = 1.4826 * float(np.median(np.abs(ls[mask] - sky))) if mask.any() else 0.0
    bas = sky + max(3 * bruit, 0.01)                       # juste au-dessus du ciel
    p60, hi = float(np.percentile(ls, 60)), float(np.percentile(ls, 99.5))
    lo = bas + (1 - float(np.clip(etendue, 0, 1))) * max(p60 - bas, 0)
    rampe = max(4 * bruit, 0.04 * (hi - lo), 1e-6)         # entrée douce dans l'objet (au-dessus du bruit), pas de bord net
    w = np.clip((ls - lo) / rampe, 0, 1)
    w = (w * w * (3 - 2 * w)).astype(np.float32)
    t = np.clip((ls - lo) / max(hi - lo, 1e-6), 0, 1) ** gamma
    a, b = hex_rgb(c1), hex_rgb(c2)
    col = a[:, None, None] * (1 - t) + b[:, None, None] * t
    col = col / np.maximum(col.mean(0, keepdims=True), 1e-6)          # même luminance que l'original
    target = np.clip(L[None] * col, 0, 1)
    k = np.clip(force, 0, 1.5) * w
    return np.clip(x * (1 - k) + target * k, 0, 1).astype(np.float32)


def hue_matrix(deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    k = 1 / 3
    sq = np.sqrt(k)
    return np.array([
        [c + (1 - c) * k, k * (1 - c) - sq * s, k * (1 - c) + sq * s],
        [k * (1 - c) + sq * s, c + k * (1 - c), k * (1 - c) - sq * s],
        [k * (1 - c) - sq * s, k * (1 - c) + sq * s, c + k * (1 - c)],
    ], np.float32)


TONE_SH, TONE_HL = 0.25, 0.20       # amplitude maximale des curseurs « ombres » et « hautes lumières »
CLARTE_SIGMA = 0.012                # rayon du contraste local, en part de la largeur de l'image (même rendu à toute taille)


def tone_curve(L, ombres, hautes):
    """Courbe de tons sur la luminance : « ombres » éclaire les tons faibles et moyens (bosse centrée vers 1/3),
    « hautes lumières » retient les tons clairs (bosse vers 3/4). Mêmes formules en JavaScript (liveTune)."""
    L = np.clip(L, 0, 1)
    s1 = L * (1 - L) ** 2 * 6.75
    s2 = L ** 3 * (1 - L) * (256 / 27)
    return np.clip(L + TONE_SH * ombres * s1 - TONE_HL * hautes * s2, 0, 1)


def box_radius(width):
    """Rayon des trois passes de flou boîte qui approchent un flou gaussien de sigma CLARTE_SIGMA x largeur."""
    sig = CLARTE_SIGMA * width
    w = np.sqrt(12 * sig * sig / 3 + 1)
    return max(1, int(round((w - 1) / 2)))


def box_blur3(L, r):
    """Trois passes de moyenne glissante (2r+1) horizontale puis verticale, bords répétés : exactement le flou de
    l'aperçu en direct (liveTune), pour que le contraste local y soit identique."""
    import cv2
    out = L.astype(np.float32)
    for _ in range(3):
        out = cv2.blur(out, (2 * r + 1, 1), borderType=cv2.BORDER_REPLICATE)
        out = cv2.blur(out, (1, 2 * r + 1), borderType=cv2.BORDER_REPLICATE)
    return out


def tune(x, prm, sky):
    """Réglage fin. prm : temperature, teinte, rotation, saturation, sat_rouge, sat_bleu, vibrance, luminosite,
    ombres, hautes_lumieres, clarte, noirs, proteger_fond. Ordre : balance, rotation, saturations, tons moyens,
    noirs, contraste local (objet seul), protection du fond, courbe ombres / hautes lumières (depuis le ciel)."""
    r, g, b = x[0].copy(), x[1].copy(), x[2].copy()
    t, m = prm.get("temperature", 0.0), prm.get("teinte", 0.0)
    r *= 1 + 0.12 * t
    b *= 1 - 0.12 * t
    g *= 1 - 0.10 * m
    y = np.stack([r, g, b])
    if prm.get("rotation", 0):
        M = hue_matrix(prm["rotation"])
        y = np.einsum("ij,jhw->ihw", M, y)
    L = y.mean(0)
    sat, vib = prm.get("saturation", 0.0), prm.get("vibrance", 0.0)
    sr, sb = prm.get("sat_rouge", 0.0), prm.get("sat_bleu", 0.0)
    mx, mn = y.max(0), y.min(0)
    s_norm = (mx - mn) / np.maximum(mx, 1e-6)
    f = (1 + sat) * (1 + vib * (1 - np.clip(s_norm, 0, 1)))
    if sr or sb:
        # part « rouge » (Hα) et « bleu-turquoise » (OIII) de la couleur de chaque pixel
        ch = np.maximum(mx - mn, 1e-6)
        wr = np.clip((y[0] - (y[1] + y[2]) / 2) / ch, 0, 1)
        wb = np.clip(((y[1] + y[2]) / 2 - y[0]) / ch, 0, 1)
        f = f * np.maximum(1 + sr * wr + sb * wb, 0)
    y = L[None] + f[None] * (y - L[None])
    gam = prm.get("luminosite", 1.0)
    y = np.clip(y, 0, 1) ** (1 / max(gam, 0.05))
    nb = prm.get("noirs", 0.0)
    if nb:
        y = np.clip((y - nb) / (1 - nb), 0, 1)
    y = np.clip(y, 0, 1)
    L0 = x.mean(0)
    w = np.clip((L0 - sky) / 0.25, 0, 1)
    w = w * w * (3 - 2 * w)                       # 0 dans le ciel, 1 dans l'objet
    cl = prm.get("clarte", 0.0)
    if cl:
        L2 = y.mean(0)
        det = L2 - box_blur3(L2, box_radius(x.shape[2]))
        y = np.clip(y + (1.5 * cl * det * w)[None], 0, 1)
    if prm.get("proteger_fond", True):
        y = x * (1 - w) + y * w
    om, hl = prm.get("ombres", 0.0), prm.get("hautes_lumieres", 0.0)
    if om or hl:
        # courbe comptée depuis le niveau du ciel : le ciel ne bouge pas, la nébuleuse faible (trop proche du ciel
        # pour échapper à la protection du fond) s'éclaire quand même
        L1 = y.mean(0)
        u = np.clip((L1 - sky) / max(1 - sky, 1e-6), 0, 1)
        L2 = sky + tone_curve(u, om, hl) * (1 - sky)
        k = np.where(L1 > sky, L2 / np.maximum(L1, 1e-6), 1.0)
        y = np.clip(y * k[None], 0, 1)
    return np.clip(y, 0, 1).astype(np.float32)


# ------------------------------------------------------------------ propositions de réglage fin (P8F)
# Mesures directes, pas de modèle : chaque proposition est calculée pour ramener une mesure vers une cible, avec
# les mêmes formules que tune() (temperature : r*(1+0.12t), b*(1-0.12t) ; teinte : g*(1-0.10m) ; noirs :
# (y-nb)/(1-nb) ; saturation : L + (1+sat)(y-L)). Les cibles sont prudentes et affichées.
SKY_TARGET = 0.07        # fond du ciel visé (luminance 0-1), comme le « niveau » par défaut des noirs (P6N)
SKY_MAX = 0.10           # au-delà : fond jugé délavé
# saturation médiane de la partie lumineuse de l'objet : (seuil « terne », cible, seuil « criard »), par type
CHROMA = {"nebuleuse": (0.30, 0.40, 0.80), "galaxie": (0.15, 0.22, 0.60)}


def _chroma(y):
    mx, mn = y.max(0), y.min(0)
    return (mx - mn) / np.maximum(mx, 1e-6)


def suggest(x, ttype="nebuleuse"):
    """x : calque couleur (3, H, W) 0-1. Retourne (réglages, lignes d'explication). Rien n'est proposé pour ce qui
    est déjà dans les cibles : sur une image correcte, les curseurs restent neutres."""
    from . import fitsio
    x = x[:, ::2, ::2] if x.shape[1] > 1200 else x
    mask = fitsio.sky_mask(x)
    r, g, b = (float(np.median(x[c][mask])) for c in range(3))
    L = (r + g + b) / 3
    prm = {"temperature": 0.0, "teinte": 0.0, "saturation": 0.0, "vibrance": 0.0, "luminosite": 1.0, "noirs": 0.0,
           "proteger_fond": True, "sat_rouge": 0.0, "sat_bleu": 0.0, "ombres": 0.0, "hautes_lumieres": 0.0, "clarte": 0.0}
    lines = [f"Fond du ciel mesuré : R/V/B {r:.3f} / {g:.3f} / {b:.3f} (luminance {L:.3f})"]
    fix_sky = False
    # dominante chaude / froide du fond : rouge et bleu égaux
    strong = []
    if r + b > 1e-4 and abs(r - b) / max(L, 1e-4) > 0.06:
        t_need = (b - r) / (0.12 * (r + b))
        t = float(np.clip(t_need, -1, 1))
        prm["temperature"] = round(t, 2)
        fix_sky = True
        lines.append(f"Dominante {'chaude (rouge > bleu)' if r > b else 'froide (bleu > rouge)'} sur le fond : "
                     f"température {t:+.2f}")
        if abs(t_need) > 1.2:
            strong.append("dominante chaude/froide")
    # fond vert / magenta : vert égal à la moyenne rouge-bleu (après la correction de température)
    r2, b2 = r * (1 + 0.12 * prm["temperature"]), b * (1 - 0.12 * prm["temperature"])
    rb = (r2 + b2) / 2
    if g > 1e-4 and abs(g - rb) / max(L, 1e-4) > 0.06:
        m_need = (1 - rb / g) / 0.10
        m = float(np.clip(m_need, -1, 1))
        if abs(m_need) > 1.2:
            strong.append("fond vert/magenta")
        prm["teinte"] = round(m, 2)
        fix_sky = True
        lines.append(f"Fond {'verdâtre' if g > rb else 'magenta'} : teinte {m:+.2f} (vers le {'magenta' if m > 0 else 'vert'})")
    # fond délavé : ramener la luminance du ciel vers la cible
    if L > SKY_MAX:
        nb = float(np.clip((L - SKY_TARGET) / (1 - SKY_TARGET), 0, 0.15))
        prm["noirs"] = round(nb, 3)
        fix_sky = True
        lines.append(f"Fond délavé ({100 * L:.0f} %, visé {100 * SKY_TARGET:.0f} %) : noirs {nb:+.3f}")
    if strong:
        lines.append("Écart trop fort pour le réglage fin (" + ", ".join(strong) + ") : curseurs au maximum, mais le "
                     "mieux est de neutraliser le fond plus tôt (P5, ou noirs canal par canal en P6N).")
    if fix_sky:
        prm["proteger_fond"] = False
        lines.append("« Protéger le fond » décoché : la correction doit aussi toucher le ciel.")
    # couleurs de l'objet : saturation moyenne de la partie lumineuse
    Lx = x.mean(0)
    obj = Lx > max(np.percentile(Lx, 85), L + 0.08)
    if obj.mean() > 0.002:
        low, target, high = CHROMA.get(ttype, CHROMA["nebuleuse"])
        c = float(np.median(_chroma(x)[obj]))
        if c < low:
            sat = float(np.clip(target / max(c, 0.05) - 1, 0.1, 0.8))
            prm["saturation"], prm["vibrance"] = round(sat, 2), 0.2
            lines.append(f"Couleurs ternes (saturation mesurée {c:.2f}, visée {target:.2f} pour une {ttype}) : "
                         f"saturation {sat:+.2f}, vibrance +0.20")
        elif c > high:
            prm["saturation"] = -0.2
            lines.append(f"Couleurs très saturées ({c:.2f}) : saturation -0.20")
        else:
            lines.append(f"Saturation de l'objet correcte ({c:.2f}) : pas de changement")
    neutral = {"temperature": 0.0, "teinte": 0.0, "saturation": 0.0, "vibrance": 0.0, "luminosite": 1.0, "noirs": 0.0,
               "proteger_fond": True}
    if all(prm[k] == v for k, v in neutral.items()):
        lines.append("Rien à corriger d'après les mesures : les curseurs restent neutres.")
    return prm, lines
