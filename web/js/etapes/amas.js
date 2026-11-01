// P7 : protéger un amas d'étoiles en dessinant un cercle sur l'image étirée (P5), au lieu de taper x,y,r,N.
// Le champ « amas » des réglages (x,y,rayon,N en pixels pleine résolution, y depuis le haut) se remplit tout seul.
import { h, S, fileUrl, stepById } from "../core.js";
import { initEditor, visible } from "../editeur.js";

export function amasPicker(step, onChange) {
  const list = initEditor(step);
  const p = step.params.find(q => q.name === "amas");
  if (!p) return null;
  const ref = stepById("P5")?.state?.retained?.previews;
  const box = h("div", { class: "amas" });
  if (!ref?.main || !ref.size) {
    box.append(h("b", {}, "Protéger un amas d'étoiles"), h("div", { class: "muted small" }, "Image de l'étape P5 introuvable : valide d'abord P5 pour dessiner le cercle ici."));
    return box;
  }
  const [W, H] = ref.size;
  const parse = (t) => { const a = String(t || "").split(",").map(Number); return a.length >= 4 && a.every(n => !isNaN(n)) ? { x: a[0], y: a[1], r: a[2], n: a[3] } : null; };
  let cur = parse((list.find(v => visible(p, v)) || list[0])?.amas);
  const save = () => {
    const txt = cur ? `${Math.round(cur.x)},${Math.round(cur.y)},${Math.round(cur.r)},${Math.round(cur.n)}` : "";
    list.forEach(v => { v.amas = txt; });            // ignoré par les autres méthodes : on le met partout
    onChange && onChange(); draw();
  };
  const draw = () => {
    box.innerHTML = "";
    const head = h("div", { class: "amas-head" }, h("b", {}, "Protéger un amas d'étoiles"), h("span", { class: "muted small" },
      " (facultatif) — la sélection par nombre peut vider un amas serré ; dessine un cercle autour, ses étoiles les plus brillantes sont gardées en plus. ",
      h("b", {}, "Clique dans l'image ci-dessous au centre de l'amas, garde le bouton enfoncé et glisse pour régler le rayon."),
      " (Les images de résultats plus bas servent seulement au zoom.)"));
    box.append(head);
    if (!list.some(v => v.methode === "selection"))
      box.append(h("div", { class: "banner warn", style: "margin:6px 0" }, "La protection ne sert qu'avec la méthode « Sélection étoile par étoile » : choisis-la dans les réglages d'au moins une variante, sinon le cercle est ignoré."));
    const img = h("img", { src: fileUrl(ref.main), draggable: "false" });
    const circ = h("div", { class: "amas-circle" });
    const stage = h("div", { class: "amas-stage" }, img, circ);
    const k = () => img.clientWidth / W;
    const place = () => {
      if (!cur || !img.clientWidth) { circ.style.display = "none"; return; }
      Object.assign(circ.style, { display: "block", left: (cur.x - cur.r) * k() + "px", top: (cur.y - cur.r) * k() + "px",
        width: 2 * cur.r * k() + "px", height: 2 * cur.r * k() + "px" });
    };
    img.onload = place;
    let drag = null;
    const pos = (e) => { const b = img.getBoundingClientRect(); return [(e.clientX - b.left) / k(), (e.clientY - b.top) / k()]; };
    Object.assign(stage.style, { cursor: "crosshair", touchAction: "none" });
    stage.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation();
      stage.setPointerCapture(e.pointerId);              // le glissé continue même si le curseur sort de l'image
      const [x, y] = pos(e); drag = { x, y }; cur = { x, y, r: cur?.r || Math.round(W / 25), n: cur?.n || 30 }; place();
    });
    stage.addEventListener("pointermove", (e) => { if (!drag) return; const [x, y] = pos(e); const r = Math.hypot(x - drag.x, y - drag.y); if (r > 4 / k()) { cur.r = r; place(); } });
    const up = () => { if (drag) { drag = null; save(); } };
    stage.addEventListener("pointerup", up);
    stage.addEventListener("pointercancel", up);
    const nIn = h("input", { type: "range", min: 5, max: 200, step: 5, value: cur?.n || 30, disabled: !cur,
      oninput: (e) => { if (cur) { cur.n = +e.target.value; nOut.textContent = cur.n; } }, onchange: save });
    const nOut = h("span", { class: "mono" }, String(cur?.n || 30));
    box.append(stage,
      h("div", { class: "amas-tools" },
        cur ? h("span", { class: "small" }, `Centre ${Math.round(cur.x)}, ${Math.round(cur.y)} · rayon ${Math.round(cur.r)} px`)
            : h("span", { class: "small muted" }, "Clique au centre de l'amas et glisse pour régler le rayon."),
        h("label", { class: "small" }, "Étoiles gardées en plus dans l'amas ", nIn, " ", nOut),
        cur ? h("button", { class: "ghost small", onclick: () => { cur = null; save(); } }, "Retirer la protection") : null));
    place();
  };
  draw();
  return box;
}
