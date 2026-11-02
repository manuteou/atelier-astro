// S4 : zones de mesure du signal/bruit dessinées à la souris sur l'aperçu du stack, au lieu de taper x,y,w,h.
// Le champ « zones » (nom:x,y,w,h ; … en pixels pleine résolution, origine en haut à gauche) se remplit tout seul.
import { h, fileUrl, stepById } from "../core.js";
import { initEditor } from "../editeur.js";

const parse = (t) => String(t || "").split(";").map(s => s.trim()).filter(Boolean).map(s => {
  const [nom, v] = s.includes(":") ? s.split(":") : ["", s];
  const a = v.split(",").map(Number);
  return a.length >= 4 && a.every(n => !isNaN(n)) ? { nom: nom.trim(), r: a.slice(0, 4) } : null;
}).filter(Boolean);

export function zonesPicker(step, onChange) {
  const list = initEditor(step);
  const src = ["S3B", "S3"].map(id => stepById(id)).find(s => s?.applies && s?.state?.retained?.previews?.main);
  const ref = src?.state?.retained?.previews;
  const box = h("div", { class: "amas zones" });
  if (!ref?.main || !ref.size) return null;
  const [W, H] = ref.size;
  let zones = parse(list[0]?.zones);
  const save = () => {
    const txt = zones.map((z, i) => `${z.nom || "zone" + (i + 1)}:${z.r.map(Math.round).join(",")}`).join(" ; ");
    list.forEach(v => { v.zones = txt; });
    onChange && onChange(); draw();
  };
  const draw = () => {
    box.innerHTML = "";
    box.append(h("div", { class: "amas-head" }, h("b", {}, "Zones à mesurer (facultatif)"), h("span", { class: "muted small" },
      " — dessine un rectangle sur une partie faible de la nébuleuse ou de la galaxie (un bras, une frange) : la mesure " +
      "dira si elle est propre, et sinon combien de temps de pose il faudrait en plus. Clique et glisse sur l'image ; " +
      "plusieurs zones possibles.")));
    const img = h("img", { src: fileUrl(ref.main), draggable: "false" });
    const stage = h("div", { class: "amas-stage" }, img);
    const k = () => img.clientWidth / W;
    const rects = [];
    const place = () => {
      rects.forEach(e => e.remove()); rects.length = 0;
      zones.forEach((z, i) => {
        const [x, y, w, hh] = z.r, s = k();
        const e = h("div", { class: "zone-rect", style: `left:${x * s}px;top:${y * s}px;width:${w * s}px;height:${hh * s}px` },
          h("span", {}, z.nom || "zone" + (i + 1)));
        stage.append(e); rects.push(e);
      });
    };
    img.onload = place;
    let drag = null, live = null;
    const pos = (e) => { const b = img.getBoundingClientRect(); return [Math.max(0, Math.min(W, (e.clientX - b.left) / k())), Math.max(0, Math.min(H, (e.clientY - b.top) / k()))]; };
    Object.assign(stage.style, { cursor: "crosshair", touchAction: "none" });
    stage.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation(); stage.setPointerCapture(e.pointerId);
      drag = pos(e);
      live = h("div", { class: "zone-rect live" }); stage.append(live);
    });
    stage.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const [x, y] = pos(e), s = k();
      Object.assign(live.style, { left: Math.min(x, drag[0]) * s + "px", top: Math.min(y, drag[1]) * s + "px",
        width: Math.abs(x - drag[0]) * s + "px", height: Math.abs(y - drag[1]) * s + "px" });
    });
    stage.addEventListener("pointerup", (e) => {
      if (!drag) return;
      const [x, y] = pos(e), r = [Math.min(x, drag[0]), Math.min(y, drag[1]), Math.abs(x - drag[0]), Math.abs(y - drag[1])];
      drag = null; live?.remove();
      if (r[2] * k() > 6 && r[3] * k() > 6) { zones.push({ nom: "", r }); save(); }
    });
    box.append(stage, h("div", { class: "amas-tools" },
      zones.length ? zones.map((z, i) => h("span", { class: "small chip" }, `${z.nom || "zone" + (i + 1)} : ${z.r.map(Math.round).join(", ")}`,
        h("button", { class: "ghost small", title: "Retirer cette zone", onclick: () => { zones.splice(i, 1); save(); } }, "✕")))
        : h("span", { class: "small muted" }, "Aucune zone : seules les deux cartes (finesse des étoiles, signal/bruit) seront produites.")));
    place();
  };
  draw();
  return box;
}
