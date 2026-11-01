// P8F : réglage fin des couleurs en direct. liveTune reproduit exactement app/color_ops.py:tune.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";
import { initEditor } from "../editeur.js";

// ------------------------------------------------------------------ réglage fin en direct (P8F)
// liveTune reproduit exactement app/color_ops.py:tune ; l'application en pleine résolution passe par Python.
export function hueMatrix(deg) {
  const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), k = 1 / 3, q = Math.sqrt(k);
  return [c + (1 - c) * k, k * (1 - c) - q * s, k * (1 - c) + q * s,
          k * (1 - c) + q * s, c + k * (1 - c), k * (1 - c) - q * s,
          k * (1 - c) - q * s, k * (1 - c) + q * s, c + k * (1 - c)];
}

export function liveTune(prm, sky, base, stars, out, original) {
  const t = +prm.temperature || 0, m = +prm.teinte || 0, rot = +prm.rotation || 0;
  const sat = +prm.saturation || 0, vib = +prm.vibrance || 0, gam = Math.max(+prm.luminosite || 1, 0.05), nb = +prm.noirs || 0;
  const prot = prm.proteger_fond !== false, M = rot ? hueMatrix(rot) : null;
  const N = 2048, lut = new Float32Array(N + 1);
  for (let i = 0; i <= N; i++) lut[i] = Math.pow(i / N, 1 / gam);
  const cl = (v) => v < 0 ? 0 : v > 1 ? 1 : v;
  const pw = (v) => { v = cl(v) * N; const i = v | 0; return i >= N ? lut[N] : lut[i] + (lut[i + 1] - lut[i]) * (v - i); };
  for (let i = 0; i < base.length; i += 4) {
    const r0 = base[i] / 255, g0 = base[i + 1] / 255, b0 = base[i + 2] / 255;
    let r = r0, g = g0, b = b0;
    if (!original) {
      r *= 1 + 0.12 * t; b *= 1 - 0.12 * t; g *= 1 - 0.10 * m;
      if (M) { const R = M[0] * r + M[1] * g + M[2] * b, G = M[3] * r + M[4] * g + M[5] * b, B = M[6] * r + M[7] * g + M[8] * b; r = R; g = G; b = B; }
      const L = (r + g + b) / 3, mx = Math.max(r, g, b), mn = Math.min(r, g, b);
      const sn = cl((mx - mn) / Math.max(mx, 1e-6));
      const f = (1 + sat) * (1 + vib * (1 - sn));
      r = pw(L + f * (r - L)); g = pw(L + f * (g - L)); b = pw(L + f * (b - L));
      if (nb) { r = cl((r - nb) / (1 - nb)); g = cl((g - nb) / (1 - nb)); b = cl((b - nb) / (1 - nb)); }
      if (prot) {
        let w = cl(((r0 + g0 + b0) / 3 - sky) / 0.25); w = w * w * (3 - 2 * w);
        r = r0 * (1 - w) + r * w; g = g0 * (1 - w) + g * w; b = b0 * (1 - w) + b * w;
      }
    }
    if (stars) {
      r = 1 - (1 - cl(r)) * (1 - stars[i] / 255); g = 1 - (1 - cl(g)) * (1 - stars[i + 1] / 255); b = 1 - (1 - cl(b)) * (1 - stars[i + 2] / 255);
    }
    out[i] = cl(r) * 255 + 0.5; out[i + 1] = cl(g) * 255 + 0.5; out[i + 2] = cl(b) * 255 + 0.5; out[i + 3] = 255;
  }
}

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
      liveTune(vals, src.sky, src.base, src.stars, img.data, showOrig);
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
