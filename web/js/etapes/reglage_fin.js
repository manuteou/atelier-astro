// P8F : réglage fin des couleurs en direct. liveTune reproduit exactement app/color_ops.py:tune.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";
import { initEditor } from "../editeur.js";
import { liveTune } from "./tune.js";
export { hueMatrix, liveTune, toneCurve, boxRadius, boxBlur3 } from "./tune.js";

// ------------------------------------------------------------------ réglage fin en direct (P8F)
// liveTune reproduit exactement app/color_ops.py:tune ; l'application en pleine résolution passe par Python.
export function loadImg(url) {
  return new Promise((ok, ko) => { const im = new Image(); im.onload = () => ok(im); im.onerror = () => ko(new Error("aperçu introuvable : " + url)); im.src = url; });
}

export function pixels(im, w, h) {
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  const x = c.getContext("2d"); x.drawImage(im, 0, 0, w, h);
  return x.getImageData(0, 0, w, h).data;
}

export function liveTuner(step) {
  const vals = initEditor(step)[0];
  const canvas = h("canvas", { class: "live-canvas" });
  const status = h("span", { class: "muted" }, "chargement de l'aperçu…");
  const wrap = h("div", { class: "live" });
  let src = null, showOrig = false, pending = false;
  const draw = () => {
    if (!src || pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      const ctx = canvas.getContext("2d");
      const img = ctx.createImageData(src.w, src.h);
      liveTune(vals, src.sky, src.base, src.stars, img.data, showOrig, src.w);
      ctx.putImageData(img, 0, 0);
    });
  };
  const sliders = h("div", { class: "live-sliders" });
  const build = () => {
    sliders.innerHTML = "";
    for (const p of step.params) {
      if (p.type === "bool") {
        sliders.append(h("label", { class: "live-check" }, h("input", { type: "checkbox", checked: vals[p.name] !== false, onchange: e => { vals[p.name] = e.target.checked; draw(); } }), p.label));
        continue;
      }
      const out = h("span", { class: "mono live-val" }, String(vals[p.name] ?? p.default));
      const rng = h("input", { type: "range", min: p.min, max: p.max, step: p.step, value: vals[p.name] ?? p.default,
        oninput: e => { vals[p.name] = parseFloat(e.target.value); out.textContent = e.target.value; draw(); },
        ondblclick: () => { vals[p.name] = p.default; build(); draw(); }, title: "double-clic : remettre à zéro" });
      sliders.append(h("div", { class: "live-row" }, h("label", {}, p.label), rng, out));
    }
  };
  build();
  const orig = h("button", { class: "ghost small", title: "Maintenir pour voir l'image avant réglage",
    onmousedown: () => { showOrig = true; draw(); }, onmouseup: () => { showOrig = false; draw(); }, onmouseleave: () => { if (showOrig) { showOrig = false; draw(); } },
    ontouchstart: () => { showOrig = true; draw(); }, ontouchend: () => { showOrig = false; draw(); } }, "Maintenir : avant");
  const reset = h("button", { class: "ghost small", onclick: () => { for (const p of step.params) vals[p.name] = p.default; build(); draw(); } }, "Tout remettre à zéro");
  // propositions calculées d'après des mesures (app/color_ops.py:suggest) : on place les curseurs, l'aperçu suit
  const why = h("div", { class: "hint suggest-why" });
  const propose = h("button", { class: "small", title: "Place les curseurs d'après des mesures de l'image (fond, dominante, saturation) ; tu ajustes ensuite",
    onclick: async () => {
      try {
        const r = await api("GET", `/api/projects/${S.project}/p8f/suggest`);
        Object.assign(vals, r.reglages); build(); draw();
        why.innerHTML = ""; why.append(h("b", {}, "Proposé d'après les mesures :"), ...r.lignes.map(l => h("div", {}, "· " + l)));
      } catch (e) { toast(e.message, true); }
    } }, "Proposer des réglages");
  wrap.append(h("div", { class: "live-view" }, canvas),
    h("div", { class: "live-panel" }, h("div", { class: "row" }, propose, orig, reset), why, sliders, status));
  (async () => {
    try {
      const L = await api("GET", `/api/projects/${S.project}/live`);
      const bi = await loadImg(fileUrl(L.base));
      const w = bi.naturalWidth, hh = bi.naturalHeight;
      const si = L.stars ? await loadImg(fileUrl(L.stars)) : null;
      src = { w, h: hh, sky: L.sky, base: pixels(bi, w, hh), stars: si ? pixels(si, w, hh) : null };
      canvas.width = w; canvas.height = hh;
      status.textContent = `aperçu ${w}×${hh} (image ${L.w}×${L.h})` + (L.stars ? ", étoiles comprises" : ", sans calque d'étoiles") +
        ` · ciel mesuré ${L.sky.toFixed(3)}. L'aperçu est en 8 bits : le rendu pleine résolution peut différer très légèrement.`;
      draw();
    } catch (e) { status.textContent = e.message; }
  })();
  return wrap;
}
