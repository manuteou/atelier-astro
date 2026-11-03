// P6H : entourer chaque reflet d'étoile brillante d'un cercle sur le calque sans étoiles (P6), au lieu de taper x,y,r.
// Le champ « reflets » (x,y,rayon ; … en pixels pleine résolution, y depuis le haut) se remplit tout seul.
import { h, fileUrl, stepById } from "../core.js";
import { initEditor } from "../editeur.js";

const parse = (t) => String(t || "").split(";").map(s => s.trim()).filter(Boolean).map(s => {
  const a = s.split(",").map(Number);
  return a.length >= 3 && a.every(n => !isNaN(n)) ? { x: a[0], y: a[1], r: a[2] } : null;
}).filter(Boolean);

export function halosPicker(step, onChange) {
  const list = initEditor(step);
  const ref = stepById("P6")?.state?.retained?.previews;
  const box = h("div", { class: "amas" });
  if (!ref?.main || !ref.size) return null;
  const [W, H] = ref.size;
  let cercles = parse(list[0]?.reflets);
  const save = () => {
    const txt = cercles.map(c => `${Math.round(c.x)},${Math.round(c.y)},${Math.round(c.r)}`).join(" ; ");
    list.forEach(v => { v.reflets = txt; });
    onChange && onChange(); draw();
  };
  const draw = () => {
    box.innerHTML = "";
    box.append(h("div", { class: "amas-head" }, h("b", {}, "Reflets à effacer (facultatif)"), h("span", { class: "muted small" },
      " — un reflet est un disque ou un anneau flou, souvent bleuté, décalé d'une étoile brillante. ",
      h("b", {}, "Clique au centre du reflet, garde le bouton enfoncé et glisse jusqu'à englober tout le reflet, bord compris."),
      " Autour d'une étoile très brillante, un seul grand cercle qui englobe tout (lueur, reflet, grand anneau) donne souvent "
      + "le résultat le plus propre. Plusieurs cercles possibles. Le cœur des étoiles brillantes est corrigé sans cercle.")));
    const img = h("img", { src: fileUrl(ref.main), draggable: "false" });
    const stage = h("div", { class: "amas-stage" }, img);
    const k = () => img.clientWidth / W;
    const circs = [];
    const place = () => {
      circs.forEach(e => e.remove()); circs.length = 0;
      cercles.forEach((c, i) => {
        const e = h("div", { class: "amas-circle", style: `display:block;left:${(c.x - c.r) * k()}px;top:${(c.y - c.r) * k()}px;` +
          `width:${2 * c.r * k()}px;height:${2 * c.r * k()}px` }, h("span", { class: "small", style: "position:absolute;top:-18px;left:0;color:#fff" }, `reflet ${i + 1}`));
        stage.append(e); circs.push(e);
      });
    };
    img.onload = place;
    let drag = null, cur = null;
    const pos = (e) => { const b = img.getBoundingClientRect(); return [(e.clientX - b.left) / k(), (e.clientY - b.top) / k()]; };
    Object.assign(stage.style, { cursor: "crosshair", touchAction: "none" });
    stage.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation(); stage.setPointerCapture(e.pointerId);
      const [x, y] = pos(e); drag = { x, y }; cur = { x, y, r: 0 }; cercles.push(cur); place();
    });
    stage.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const [x, y] = pos(e); cur.r = Math.hypot(x - drag.x, y - drag.y); place();
    });
    const up = () => {
      if (!drag) return;
      drag = null;
      if (cur.r * k() < 6) cercles.pop();
      save();
    };
    stage.addEventListener("pointerup", up);
    stage.addEventListener("pointercancel", up);
    box.append(stage, h("div", { class: "amas-tools" },
      cercles.length ? cercles.map((c, i) => h("span", { class: "small chip" }, `reflet ${i + 1} : ${Math.round(c.x)}, ${Math.round(c.y)}, r ${Math.round(c.r)}`,
        h("button", { class: "ghost small", title: "Retirer ce cercle", onclick: () => { cercles.splice(i, 1); save(); } }, "✕")))
        : h("span", { class: "small muted" }, "Aucun reflet entouré : seuls le cœur et la lueur des étoiles brillantes seront corrigés.")));
    place();
  };
  draw();
  return box;
}
