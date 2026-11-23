// Ciel des prochaines nuits : nuages pendant la nuit noire, Lune, vent, buée, et prochain soir favorable.
// Prévisions Open-Meteo pour la ville des Réglages (calcul côté serveur : /api/meteo).
import { h, api, openDlg } from "./core.js";

const COUL = { favorable: "#3ccf8e", possible: "#f2b84b", "défavorable": "#e2685f" };

// vert (ciel dégagé) -> jaune -> rouge (couvert)
const teinte = (nuages) => `hsl(${Math.round(130 * (1 - Math.max(0, Math.min(100, nuages)) / 100))} 70% 52%)`;

function barres(heures) {
  // une barre par heure de nuit : pleine hauteur et rouge = ciel couvert ; basse et verte = dégagé
  return h("div", { class: "ciel-barres", title: "couverture nuageuse heure par heure pendant la nuit noire" },
    heures.map(x => h("i", { class: x.ok ? "ok" : "", style: `height:${Math.max(10, x.nuages)}%;background:${teinte(x.nuages)}`, title: `${x.h} h : ${x.nuages} % de nuages` })));
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
      h("div", { class: "ciel-pct", style: `color:${teinte(n.nuages)}` }, `${n.nuages} %`, h("span", { class: "muted small" }, " nuages")),
      h("div", { class: "ciel-obs" }, n.heures_observables ? `${n.heures_observables} h` : "0 h", h("span", { class: "muted small" }, " observables")),
      h("div", { class: "small ciel-creneaux" }, n.creneaux.length ? n.creneaux.map(c => h("div", {}, `${c.debut.slice(0, 2)} h–${c.fin.slice(0, 2)} h (${c.heures} h)`)) : "—"),
      h("div", { class: "small muted" }, n.lune_pct < 8 ? "sans Lune" : `Lune ${n.lune_pct} %`),
      h("div", { class: "ciel-avis", style: `color:${COUL[n.avis]}` }, n.avis + (n.tendance ? " ?" : ""))))));
  box.append(h("div", { class: "muted small" }, `Nuages comptés pendant la nuit noire seulement (Soleil sous −18°). Une heure est observable quand la couverture nuageuse ne dépasse pas ${d.seuil} % (réglable) ; les heures observables qui se suivent forment un créneau. La note juge le ciel dégagé, sa durée, la Lune, le vent et la buée ; pas la turbulence ni la transparence. Fiable à 2-3 jours, tendance au-delà.`));
  return box;
}

// Accueil : la prévision suit le jour courant (fenêtre glissante), même si la page reste ouverte des jours :
// redemandée toutes les 30 min, au retour sur l'onglet si elle a plus de 30 min, et au changement de jour.
export function cielAccueil(el) {
  let t = 0, jour = "";
  const maj = async () => {
    t = Date.now(); jour = new Date().toDateString();
    const box = await cielPanel();
    el.replaceChildren(box);
  };
  maj();
  setInterval(() => { if (Date.now() - t > 30 * 60e3 || new Date().toDateString() !== jour) maj(); }, 60e3);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && (Date.now() - t > 30 * 60e3 || new Date().toDateString() !== jour)) maj();
  });
}

export async function dlgCiel() {
  openDlg("Ciel des prochaines nuits", await cielPanel());
}
