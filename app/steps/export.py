"""Export (étape 12) et fiche PDF (étape 13)."""
import html
import shutil
from pathlib import Path

import numpy as np

from .. import checks, fitsio, signature
from .base import P, Step
from .lineaire import tool


def unique(path):
    path = Path(path)
    if not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name(f"{path.stem}_v{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def finals(p):
    return p.latest("fusion_ret", "fusion_nxt", "fusion"), p.latest("naturel_ret", "naturel_nxt", "naturel")


class Export(Step):
    id, phase = "P12", "3 · Couleurs et export"
    title = "Export"
    help = ("Produit un JPEG haute définition, un JPEG réduit pour le partage et un TIFF 16 bits, plus les trois images "
            "de la fiche : image brute, version naturelle, version colorisée. La rotation se fait par quarts de tour "
            "exacts, sans perte ; elle s'applique aux images finales, pas à l'image brute du stack, qui sert de repère : "
            "la colonne « Réf. » montre le stack recadré, tourne les finales pour qu'elles soient dans le même sens. "
            "Un nouvel export ne remplace jamais le précédent (_v2, _v3…).")
    params = [P("rotation", "Rotation", "choice", "0", choices=[["0", "aucune"], ["90", "90° horaire"],
                                                               ["180", "180°"], ["270", "90° anti-horaire"]]),
              P("miroir", "Miroir horizontal", "bool", False),
              P("partage", "Largeur du JPEG de partage", "int", 1600, 600, 4000, 100),
              P("tiff", "TIFF 16 bits", "bool", True),
              P("signer", "Signer l'image", "choice", "partage",
                choices=[["non", "non"], ["partage", "JPEG de partage"], ["partage_hd", "JPEG de partage et JPEG HD"]],
                help="le FIT et le TIFF ne sont jamais signés : ce sont tes fichiers de travail"),
              P("titre", "Nom de l'objet", "text", "", show_if={"signer": ["partage", "partage_hd"]},
                help="ex. « Sh2-132 · nébuleuse du Lion » ; vide = pas de nom"),
              P("signature", "Signature", "text", "", show_if={"signer": ["partage", "partage_hd"]},
                help="ex. « © Manu · Seestar S50 » ; retenue pour tes prochains projets"),
              P("position", "Position", "choice", "bas_droite", choices=[list(x) for x in signature.POSITIONS],
                show_if={"signer": ["partage", "partage_hd"]}),
              P("taille_texte", "Taille du texte", "float", 1.0, 0.5, 2.0, 0.1, show_if={"signer": ["partage", "partage_hd"]}),
              P("opacite", "Opacité", "float", 0.85, 0.3, 1.0, 0.05, show_if={"signer": ["partage", "partage_hd"]})]
    preview_key = "final"

    def compose_preview(self, ctx, outputs, tag=""):
        """Aperçu de la carte : la finale tournée comme les fichiers exportés (sinon la carte la montrerait non tournée)."""
        prm = getattr(self, "_last_prm", {}) or {}
        d, h = fitsio.read(ctx.p.abs(outputs["final"]))
        rgb = fitsio.orient(fitsio.display(d, h), int(prm.get("rotation", 0) or 0), bool(prm.get("miroir")))
        hh = h.copy()
        hh["ROWORDER"] = "TOP-DOWN"
        out = ctx.out(tag, "apercu_oriente")
        fitsio.write(out, np.transpose(rgb, (2, 0, 1)), hh)
        return out
    linear = False
    reference_step = "P0"            # le stack recadré : repère d'orientation pour la rotation des finales

    def ready(self, p):
        return (finals(p)[0] is not None, "valider d'abord la fusion (P9)")

    def run(self, ctx, prm, tag):
        p = ctx.p
        T = p.T
        fin, nat = finals(p)
        rot, mir = int(prm["rotation"]), prm["miroir"]
        self._last_prm = prm
        ex = p.root / "exports"
        ex.mkdir(exist_ok=True)
        # stack brut : T_crop éclairci par Siril (autostretch lié), dans son sens d'origine : la rotation sert à mettre
        # les finales dans le même sens que lui, elle ne s'applique donc pas à lui
        brut_fit = ctx.out(tag, "brut_etire")
        tool(ctx, p.file("crop"), brut_fit, ["autostretch -linked"], "export_brut")
        files, info = {}, []

        def rgb(path):
            d, h = fitsio.read(path)
            return fitsio.orient(fitsio.display(d, h), rot, mir)
        c = rgb(fin)
        f_fit = unique(ex / f"{T}_FINAL.fit")
        shutil.copy2(fin, f_fit)
        f_hd = unique(ex / f"{T}_FINAL_colorise_HD.jpg")
        fitsio.save_jpeg(c, f_hd, 100)
        f_sh = unique(ex / f"{T}_FINAL_partage.jpg")
        sig = prm.get("signer", "non") != "non" and (prm.get("titre", "").strip() or prm.get("signature", "").strip())
        signe = (lambda img: signature.signer(img, prm.get("titre", ""), prm.get("signature", ""), prm.get("position", "bas_droite"),
                                              prm.get("taille_texte", 1.0), prm.get("opacite", 0.85))) if sig else None
        size = fitsio.save_jpeg(signe(c) if signe else c, f_sh, 88, width=min(prm["partage"], c.shape[1] - 1))
        files.update(fit=f_fit, colorise=f_hd, partage=f_sh)
        if prm["tiff"]:
            f_tif = unique(ex / f"{T}_FINAL.tif")
            fitsio.save_tiff16(c, f_tif)
            files["tiff"] = f_tif
        n = rgb(nat)
        f_nat = unique(ex / f"{T}_FINAL_naturel_HD.jpg")
        fitsio.save_jpeg(n, f_nat, 100)
        files["naturel"] = f_nat
        f_br = unique(ex / f"{T}_stack_brut_HD.jpg")
        db, hb = fitsio.read(brut_fit)
        fitsio.save_jpeg(fitsio.display(db, hb), f_br, 100)
        files["brut"] = f_br
        same = np.allclose(c[::8, ::8], n[::8, ::8], atol=1 / 255)
        info.append(f"Colorisée HD {c.shape[1]}x{c.shape[0]} · partage {size[0]}x{size[1]} · rotation {rot}°"
                    + (" + miroir" if mir else ""))
        if same:
            info.append("La finale naturelle est identique à la colorisée (aucune couleur ajoutée) : noté.")
        txt = ctx.py("controle.py", ["export", f_hd, fin, "--autre", nat], check=False)
        keep = [l.strip() for l in txt.splitlines() if l.startswith(("OK", "ATTENTION"))]
        if rot or mir:     # ses contrôles d'orientation et de correspondance ne savent pas défaire une rotation
            keep = [l for l in keep if "orientation" not in l and "correspond" not in l]
        info += keep[:5]
        info += checks.export_matches(f_hd, fin, nat if not same else None, rot, mir, "JPEG colorisé")
        info += checks.export_matches(f_nat, nat, fin if not same else None, rot, mir, "JPEG naturel")
        dfin, hfin = fitsio.read(fin)
        info += checks.borders_left(dfin, hfin, "l'image finale", zeros_only=True)
        if signe:                   # après les contrôles de correspondance, faits sur l'image vierge
            if prm["signer"] == "partage_hd":
                fitsio.save_jpeg(signe(c), f_hd, 100)
                fitsio.save_jpeg(signe(n), f_nat, 100)
            info.append(f"Signé ({'JPEG de partage et HD' if prm['signer'] == 'partage_hd' else 'JPEG de partage'}) : "
                        + " · ".join(x for x in (prm.get("titre", "").strip(), prm.get("signature", "").strip()) if x)
                        + " ; FIT et TIFF non signés")
        rels = {k: ctx.rel(v) for k, v in files.items()}
        return {"outputs": {"final": ctx.rel(fin)}, "images": [rels["colorise"], rels["naturel"], rels["brut"]],
                "info": info, "extra": {"exports": rels, "rotation": rot, "miroir": mir, "identiques": bool(same)}}

    def dyn_defaults(self, p):
        from .. import config
        f = p.state.get("fiche") or {}
        usuel = (f.get("nom_usuel") or (p.state.get("fiche_ollama") or {}).get("fields", {}).get("nom_usuel") or "").strip()
        nom = p.state.get("target") or ""
        return {"titre": f"{nom} · {usuel}" if usuel and usuel.lower() not in nom.lower() else nom,
                "signature": config.load().get("signature", "")}

    def on_validate(self, p, var):
        from .. import config
        prm = var.get("params", {})
        if prm.get("signer", "non") != "non" and prm.get("signature", "").strip():
            config.set_value("signature", prm["signature"].strip())      # retenue pour les prochains projets
        p.state["facts"]["exports"] = var["extra"]["exports"]
        p.state["facts"]["export_orient"] = [var["extra"]["rotation"], var["extra"]["miroir"]]

    def notes(self, p, st):
        e = p.state["facts"].get("exports", {})
        return "Export :\n" + "\n".join(f"  {k} : {v}" for k, v in e.items())


# ------------------------------------------------------------------ fiche ---
def fmt_ra(deg):
    h = deg / 15
    hh, mm = int(h), int((h % 1) * 60)
    ss = ((h * 60) % 1) * 60
    return f"{hh} h {mm:02d} min {ss:04.1f} s"


def fmt_dec(deg):
    s = "+" if deg >= 0 else "−"
    d = abs(deg)
    return f"{s}{int(d)}° {int((d % 1) * 60):02d}' {((d * 60) % 1) * 60:02.0f}\""


def tech_facts(p):
    f = p.state["facts"]
    out = {}
    out["date"] = (f.get("date") or "")[:10]
    tot, cnt = f.get("total"), f.get("stackcnt")
    if f.get("stacks"):
        out["poses"] = f"{tot} acquises ; " + ", ".join(f"{k} {v[0]}" for k, v in f["stacks"].items()) + " retenues"
        live = sum(float(v[1] or 0) for v in f["stacks"].values())
    else:
        out["poses"] = f"{tot} acquises, {cnt} retenues" if tot and cnt else ""
        live = float(f.get("livetime") or 0)
    hm = lambda s: f"{int(s // 3600)} h {int((s % 3600) // 60):02d} min"
    out["integration"] = hm(live) if live else ""
    multi = f.get("multi") or {}
    used_devs = None
    if f.get("groups") and multi:
        from .stacking import model
        pr = multi.get("principal")
        used_devs = [pr] if multi.get("mode") == "principal" else (
            [d for d in f["groups"] if d != pr] if multi.get("mode") == "secondaire" else list(f["groups"]))
        g = {d: f["groups"][d] for d in used_devs if d in f["groups"]}
        out["poses"] = " ; ".join(f"{model(p, d)} : {v.get('total')} acquises, {v.get('stackcnt')} retenues" for d, v in g.items())
        out["integration"] = " + ".join(f"{model(p, d)} {hm(float(v.get('livetime') or 0))}" for d, v in g.items())
    ra = dec = scale = None
    crop = p.file("crop")
    h = fitsio.header(crop) if crop else {}
    if h and h.get("CRVAL1") is not None:
        ra, dec = float(h["CRVAL1"]), float(h["CRVAL2"])
        cd = h.get("CDELT2") or h.get("CD2_2")
        if cd:
            scale = abs(float(cd)) * 3600
    if ra is None and f.get("ra") is not None:
        try:
            ra, dec = float(f["ra"]), float(f["dec"])
        except Exception:
            pass
    if scale is None and f.get("focal") and f.get("pix"):
        scale = 206.265 * float(f["pix"]) / float(f["focal"])
    out["ra"], out["dec"] = ra, dec
    out["centre"] = f"AD {fmt_ra(ra)} · Déc {fmt_dec(dec)}" if ra is not None else ""
    if scale and h:
        w, hh = h.get("NAXIS1"), h.get("NAXIS2")
        out["echelle"] = f"{scale:.2f}\"/pixel"
        out["champ"] = f"{w * scale / 60:.0f}' x {hh * scale / 60:.0f}'"
    b, q = p.state.get("bortle"), f.get("qualite_ciel") or {}
    ciel = [f"Bortle {b}" if b else ""]
    if q.get("sqm"):
        ciel.append(f"mesuré {q['sqm']:.1f} mag/arcsec² (≈ Bortle {q['bortle']})")
    out["ciel"] = " · ".join(c for c in ciel if c)
    filters = sorted({s.get("filter") for s in p.state.get("sessions", []) if s.get("filter")})
    if p.mode == "C":
        filters = [p.state.get("filtre_c")]
    roles = ""
    if p.mode == "B":
        roles = " (LP pour la nébuleuse, IRCUT pour les étoiles)" if p.type == "nebuleuse" else " (IRCUT pour la galaxie, LP pour les régions HII)"
    from .. import materiel
    from .stacking import devices as _devs
    devs0 = _devs(p) or [s.get("device") for s in p.state.get("sessions", [])][:1]
    fnames = sorted({s.get("filter_name") or s.get("filter") for s in p.state.get("sessions", []) if s.get("filter")
                     and (p.mode != "C" or s.get("filter") == p.state.get("filtre_c"))})
    filters = fnames or filters
    out["materiel"] = f"{materiel.name(p, devs0[0]) if devs0 else '?'}, filtre {' + '.join(filters)}{roles}"
    if used_devs and len(used_devs) > 1:
        out["materiel"] = (f"{' + '.join(model(p, d) for d in used_devs)} (stacks combinés, alignés sur le "
                           f"{model(p, multi.get('principal'))}), filtre {' + '.join(filters)}")
    elif used_devs:
        out["materiel"] = f"{model(p, used_devs[0])}, filtre {' + '.join(filters)}"
    st = p.state["steps"]
    used = ["Siril"]
    from .. import config, outils
    cfg = config.load()
    if multi.get("graxpert") and st.get("S3B", {}).get("status") == "done":
        used.append(outils.nom(cfg, "fond"))
    for sid, name in (("P1", outils.nom(cfg, "fond")), ("P3", outils.nom(cfg, "nettete")),
                      ("P4", outils.nom(cfg, "debruitage")), ("P6", outils.nom(cfg, "etoiles"))):
        if st.get(sid, {}).get("status") == "done" and name not in used:
            used.append(name)
    if st.get("P5", {}).get("params", {}).get("methode") == "statistical":
        used.append("Statistical Stretch")
    used.append("scripts Python astro-siril")
    out["logiciels"] = ", ".join(used)
    return out


def para(text):
    """Texte saisi -> paragraphes reportlab sûrs (échappement, lignes vides = nouveaux paragraphes)."""
    parts = [x.strip() for x in str(text or "").split("\n\n") if x.strip()]
    return [html.escape(x).replace("\n", "<br/>") for x in parts]


class Fiche(Step):
    id, phase, kind, optional = "P13", "Fiche", "formulaire", True
    title = "Fiche PDF de la cible"
    help = ("Fiche de 6-7 pages : couverture, localisation avec carte du ciel et constellations (d3-celestial, "
            "connexion internet nécessaire), histoire et origine du nom, anecdote, stack brut, deux finales, fiche "
            "technique remplie depuis le projet. Pré-remplis d'après les données : lieu (coordonnées des poses -> ville "
            "et région), localisation (constellation, coordonnées), visibilité (calculée pour ton lieu), phrases sur les "
            "images. Les textes d'histoire peuvent être proposés par Ollama (bouton « Brouillon des textes ») : ce sont "
            "des brouillons à vérifier, un petit modèle sans internet se trompe facilement de date ou de distance. "
            "Une ligne vide sépare les paragraphes. Lieu : région ou ville seulement, ou rien.")
    params = [
        P("nom_technique", "Nom technique (titre de la fiche)", "text", "",
          help="désignation de catalogue, ex. NGC 281 ; lue dans les poses, sinon proposée par le brouillon Ollama"),
        P("nom_usuel", "Nom usuel (sous-titre)", "text", ""),
        P("lieu", "Lieu de prise de vue (vide = aucun)", "text", ""),
        P("contexte", "Localisation : contexte", "textarea", ""),
        P("taille", "Taille apparente", "text", ""),
        P("catalogues", "Catalogues", "text", ""),
        P("visibilite", "Visibilité", "textarea", ""),
        P("decouverte", "Découverte", "textarea", ""),
        P("nom", "Pourquoi ce nom", "textarea", ""),
        P("nature", "Nature physique, distance", "textarea", ""),
        P("anecdote", "Anecdote sur la cible", "textarea", ""),
        P("intro_brut", "Phrase sur l'image brute", "textarea", ""),
        P("intro_finales", "Phrase sur les images finales", "textarea", ""),
        P("sources", "Sources", "textarea", ""),
        P("champ_carte", "Champ de la carte (°)", "float", 60, 40, 90, 5),
    ]
    preview_key = None

    def ready(self, p):
        return (bool(p.state["facts"].get("exports")), "valider d'abord l'export (P12)")

    def dyn_defaults(self, p):
        """Pré-remplissage : d'abord ce qui se déduit des données, puis ce que tu as déjà saisi (prioritaire)."""
        from ..fiche_auto import auto_fields
        out = {}
        if self.ready(p)[0]:
            try:
                had = "fiche_auto" in p.state and "lieu" in p.state["fiche_auto"]
                out = {k: v for k, v in auto_fields(p).items() if v}
                if not had:
                    p.save()
            except Exception:
                out = {}
        if p.state.get("fiche"):              # fiche déjà validée : tes valeurs, même un lieu laissé vide exprès
            out.update(p.state["fiche"])
        return out

    def run(self, ctx, prm, tag):
        from .. import fiche_engine as E
        from reportlab.platypus import Paragraph, Spacer, KeepTogether, HRFlowable, SimpleDocTemplate
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        p = ctx.p
        S = E.styles
        tf = tech_facts(p)
        ex = {k: p.abs(v) for k, v in p.state["facts"]["exports"].items()}
        out_dir = p.root / "fiche"
        img_dir = out_dir / "img"
        raw = E.prepare_image(str(ex["brut"]), str(img_dir))
        nat = E.prepare_image(str(ex["naturel"]), str(img_dir))
        col = E.prepare_image(str(ex["colorise"]), str(img_dir))
        from ..fiche_auto import technical_name
        cible = prm.get("nom_technique", "").strip() or technical_name(p) or p.state["target"]
        info = []
        cmap = str(out_dir / "constellation_map.jpg")
        const = None
        if tf.get("ra") is not None:
            const = E.make_constellation_map(tf["ra"], tf["dec"], cmap, fov_deg=prm["champ_carte"], target_label=cible,
                                             cache_dir=str(p.root.parent / "_celestial"))
        if const is None:
            info.append("ATTENTION : pas de carte du ciel (coordonnées absentes ou données d3-celestial injoignables). "
                        "Aucune carte n'est inventée.")
        E.PAGE_FOOTER_TEXT = f"{cible} — {prm['nom_usuel']} · Fiche d'observation" if prm["nom_usuel"] else f"{cible} · Fiche d'observation"
        v = lambda x: html.escape(str(x)) if x else "non renseigné"
        story = [Spacer(1, 0.4 * cm), Paragraph("FICHE D&rsquo;OBSERVATION &middot; ASTROPHOTOGRAPHIE", S["Kicker"]),
                 Paragraph(html.escape(cible), S["DocTitle"])]
        if prm["nom_usuel"]:
            story.append(Paragraph(html.escape(prm["nom_usuel"]), S["DocSubtitle"]))
        mat = str(tf.get("materiel", "")).split(", filtre")[0].split(" (stacks")[0]
        cap = f"{html.escape(mat)} · {v(tf.get('poses'))} · intégration {v(tf.get('integration'))}"
        if prm["lieu"]:
            cap = html.escape(prm["lieu"]) + " · " + cap
        story += [Spacer(1, 6), Paragraph(cap, S["BodyItalic"])] + E.divider(10, 14)
        story.append(E.section_heading("01", "Localisation dans le ciel"))
        story += [Paragraph(t, S["Body"]) for t in para(prm["contexte"])]
        story += [E.fact_row([("CONSTELLATION", v(const)), ("COORDONNÉES (J2000)", v(tf.get("centre")))]), Spacer(1, 8),
                  E.fact_row([("TAILLE APPARENTE", v(prm["taille"])), ("CATALOGUES", v(prm["catalogues"]))]), Spacer(1, 10)]
        story += [Paragraph(t, S["Body"]) for t in para(prm["visibilite"])]
        if const is not None:
            story.append(Spacer(1, 8))
            story += E.full_width_image(cmap, "CARTE DU CIEL",
                                        f"Champ affiché : {prm['champ_carte']:g}° &middot; constellation : {html.escape(const or 'voir texte')} "
                                        "&middot; repère rouge sur la cible &middot; N en haut, E à gauche &middot; données : d3-celestial", 13.5)
        story += E.divider()
        story.append(E.section_heading("02", "Son histoire"))
        for k in ("decouverte", "nom", "nature"):
            story += [Paragraph(t, S["Body"]) for t in para(prm[k])]
        story += E.divider()
        if prm["anecdote"].strip():
            story.append(E.section_heading("03", "Une anecdote à son propos"))
            story += [Paragraph(t, S["Body"]) for t in para(prm["anecdote"])]
        blk = [E.section_heading("04", "L&rsquo;image brute, sortie du stacking")]
        blk += [Paragraph(t, S["Body"]) for t in para(prm["intro_brut"])]
        blk += E.full_width_image(raw, "STACK BRUT — APERÇU AUTOSTRETCH",
                                  f"{v(tf.get('poses'))} · intégration {v(tf.get('integration'))}", 16.5)
        story.append(KeepTogether(blk))
        blk = [E.section_heading("05", "Les images finales")]
        blk += [Paragraph(t, S["Body"]) for t in para(prm["intro_finales"])]
        blk += E.full_width_image(nat, "VERSION FINALE — COULEURS NATURELLES",
                                  "même cadrage et même étirement, sans renforcement de couleur", 15.5)
        story.append(KeepTogether(blk))
        story.append(Spacer(1, 10))
        cstep = p.state["steps"].get("P8", {})
        from . import STEP_MAP
        story += E.full_width_image(col, "VERSION FINALE — COLORISÉE",
                                    html.escape(STEP_MAP["P8"].notes(p, cstep)) if cstep.get("params") else "", 16.5)
        from ..pipeline import notes_lines
        steps_txt = [html.escape(l) for l in notes_lines(p, short=True)]
        fiche = [E.section_heading("06", "Fiche technique"), Spacer(1, 4),
                 E.fact_row([("DATE DE LA NUIT", v(tf.get("date"))), ("POSES", v(tf.get("poses")))]), Spacer(1, 6),
                 E.fact_row([("INTÉGRATION", v(tf.get("integration"))), ("MATÉRIEL", v(tf.get("materiel")))]), Spacer(1, 6),
                 E.fact_row([("CENTRE DE L&rsquo;IMAGE (J2000)", v(tf.get("centre"))), ("CHAMP", v(tf.get("champ")))]), Spacer(1, 6),
                 E.fact_row([("ÉCHELLE", v(tf.get("echelle"))), ("LOGICIELS", v(tf.get("logiciels")))])]
        lieu_ciel = [(k, x) for k, x in (("LIEU", html.escape(prm["lieu"]) if prm["lieu"] else ""),
                                          ("CIEL", html.escape(tf.get("ciel") or ""))) if x]
        if lieu_ciel:
            fiche += [Spacer(1, 6), E.fact_row(lieu_ciel)]
        fiche.append(Spacer(1, 8))
        fiche += [Paragraph("&bull; " + e, S["Body"]) for e in steps_txt]
        story.append(KeepTogether(fiche))
        if prm["sources"].strip():
            story += [Spacer(1, 14), HRFlowable(width="100%", thickness=0.6, color=E.LINE, spaceBefore=0, spaceAfter=8)]
            story += [Paragraph(t, S["Footer"]) for t in para(prm["sources"])]
        for k in ("contexte", "decouverte", "nom", "nature", "anecdote"):
            miss = E.check_glyphs(" ".join(para(prm[k])))
            if miss:
                info.append(f"ATTENTION : caractères absents de la police dans « {k} » : {''.join(miss)}")
        pdf = unique(out_dir / f"{p.T}_fiche.pdf")
        doc = SimpleDocTemplate(str(pdf), pagesize=A4, leftMargin=E.MARGIN, rightMargin=E.MARGIN, topMargin=1.7 * cm,
                                bottomMargin=1.9 * cm, title=f"{cible} — Fiche d'observation", subject="Astrophotographie")
        doc.build(story, onFirstPage=E.draw_background, onLaterPages=E.draw_background)
        pages = render_pages(pdf, out_dir / f"pages_r{ctx.run_no}{tag}")
        info.append(f"PDF : {pdf.name}, {len(pages) or '?'} pages")
        empty = [k for k in ("contexte", "decouverte", "nom", "anecdote", "sources") if not prm[k].strip()]
        if empty:
            info.append("Champs vides (sections réduites) : " + ", ".join(empty))
        miss_tech = [k for k in ("date", "poses", "integration", "centre", "champ", "echelle") if not tf.get(k)]
        if miss_tech:
            info.append("Fiche technique « non renseigné » pour : " + ", ".join(miss_tech))
        return {"outputs": {}, "info": info, "images": [ctx.rel(x) for x in pages],
                "extra": {"pdf": ctx.rel(pdf)}, "pdf": ctx.rel(pdf)}

    def on_validate(self, p, var):
        p.state["fiche"] = var["params"]
        p.state["facts"]["fiche_pdf"] = var["extra"]["pdf"]

    def notes(self, p, st):
        return f"Fiche PDF : {p.state['facts'].get('fiche_pdf', '')}"


def render_pages(pdf, out_dir):
    try:
        import pypdfium2 as pdfium
    except Exception:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf))
    res = []
    for i in range(len(doc)):
        img = doc[i].render(scale=1.2).to_pil()
        f = out_dir / f"page_{i + 1}.jpg"
        img.convert("RGB").save(f, quality=85)
        res.append(f)
    return res


STEPS = [Export(), Fiche()]
