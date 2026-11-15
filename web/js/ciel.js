// Ciel des prochaines nuits : nuages pendant la nuit noire, Lune, vent, buée, et prochain soir favorable.
// Prévisions Open-Meteo pour la ville des Réglages (calcul côté serveur : /api/meteo).
import { h, api, openDlg } from "./core.js";

const COUL = { favorable: "#3ccf8e", possible: "#f2b84b", "défavorable": "#6b7389" };

function barres(heures) {
  // une barre par heure de nuit : pleine hauteur = ciel couvert
  return h("div", { class: "ciel-barres", title: "couverture nuageuse heure par heure pendant la nuit noire" },
    heures.map(x => h("i", { style: `height:${Math.max(6, x.nuages)}%;opacity:${0.35 + 0.65 * x.nuages / 100}`, title: `${x.h} h : ${x.nuages} % de nuages` })));
}

export async function cielPanel() {
  const box = h("div", { class: "ciel" }, h("div", { class: "muted small" }, "Prévisions du ciel…"));
  let d;
  try { d = await api("GET", "/api/meteo"); } catch (e) { d = { erreur: e.message }; }
  box.innerHTML = "";
  if (d.erreur) { box.append(h("div", { class: "muted small" }, "Ciel des prochaines nuits : " + d.erreur)); return box; }
  const p = d.prochain;
  box.append(h("div", { class: "ciel-tete" }, h("b", {}, "Ciel des prochaines nuits"),
    h("span", { class: "muted small" }, ` — ${d.lieu} (${d.origine}) · ${d.source}, ${d.maj}`)));
  box.append(h("div", { class: "ciel-prochain " + (p ? p.choix : "aucun") },
    p ? [h("b", {}, p.choix === "favorable" ? "Prochain soir favorable : " : "Pas de soir vraiment favorable ; le meilleur créneau : "),
         `${p.jour}, ${p.details[0]}`, p.details.length > 1 ? " · " + p.details.slice(1).join(" · ") : "",
         p.tendance ? h("span", { class: "muted" }, " (à plus de 3 jours : tendance à confirmer)") : null]
      : "Aucun soir favorable dans les 7 nuits à venir : ciel couvert ou créneaux trop courts."));
  box.append(h("div", { class: "ciel-nuits" }, d.nuits.map(n =>
    h("div", { class: "ciel-nuit" + (n.tendance ? " tendance" : ""), title: n.details.join(" · ") + (n.tendance ? " — tendance, à confirmer" : "") },
      h("div", { class: "ciel-jour" }, n.jour),
      barres(n.heures),
      h("div", { class: "ciel-pct" }, `${n.nuages} %`, h("span", { class: "muted small" }, " nuages")),
      h("div", { class: "small" }, n.heures_degagees ? `${n.debut} → ${n.fin}` : "—"),
      h("div", { class: "small muted" }, n.lune_pct < 8 ? "sans Lune" : `Lune ${n.lune_pct} %`),
      h("div", { class: "ciel-avis", style: `color:${COUL[n.avis]}` }, n.avis + (n.tendance ? " ?" : ""))))));
  box.append(h("div", { class: "muted small" }, "Nuages comptés pendant la nuit noire seulement (Soleil sous −18°). La note juge le ciel dégagé, sa durée, la Lune, le vent et la buée ; pas la turbulence ni la transparence. Fiable à 2-3 jours, tendance au-delà."));
  return box;
}

export async function dlgCiel() {
  openDlg("Ciel des prochaines nuits", await cielPanel());
}
