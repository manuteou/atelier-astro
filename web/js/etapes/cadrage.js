// P0 : cadre dessiné à la souris sur l'aperçu du stack.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";
import { initEditor } from "../editeur.js";
import { pixels } from "../etapes/reglage_fin.js";
import { renderMain } from "../page.js";

// ------------------------------------------------------------------ cadrage à la souris
export const RATIOS = [["libre", 0], ["1:1", 1], ["3:2", 1.5], ["2:3", 2 / 3], ["4:3", 4 / 3], ["3:4", 0.75], ["16:9", 16 / 9], ["9:16", 9 / 16]];

export function cropper(step, onChange) {
  const ref = stepById(step.reference);
  const pv = ref?.state?.retained?.previews;
  if (!pv?.main || !pv.size) return h("div", { class: "banner warn" }, "Pas encore d'aperçu du stack : valide d'abord l'empilement.");
  const [W, H] = pv.size;
  const list = initEditor(step);
  S.cropIdx = Math.min(S.cropIdx || 0, list.length - 1);
  const vals = () => list[S.cropIdx];
  if (!vals().rect) vals().rect = (step.dyn && step.dyn.rect) || [0, 0, W, H];
  let ratio = S.cropRatio || 0;
  const wrap = h("div", { class: "cropper" });
  const img = h("img", { src: fileUrl(pv.main), draggable: "false" });
  const box = h("div", { class: "cbox" }, ["nw", "n", "ne", "e", "se", "s", "sw", "w"].map(d => h("span", { class: "hdl " + d, "data-h": d })));
  const stage = h("div", { class: "cstage" }, img, box);
  const size = h("span", { class: "mono" });
  const k = () => img.clientWidth / W;                       // pixels écran par pixel pleine résolution
  const clamp = (r) => {
    let [x, y, w, hh] = r.map(Math.round);
    w = Math.max(16, Math.min(w, W)); hh = Math.max(16, Math.min(hh, H));
    x = Math.max(0, Math.min(x, W - w)); y = Math.max(0, Math.min(y, H - hh));
    return [x, y, w, hh];
  };
  const draw = () => {
    const [x, y, w, hh] = vals().rect, s = k();
    Object.assign(box.style, { left: x * s + "px", top: y * s + "px", width: w * s + "px", height: hh * s + "px" });
    const g = (a, b) => b ? g(b, a % b) : a, d = g(w, hh);
    size.textContent = `x ${x} · y ${y} · ${w} x ${hh} px` + (w / d <= 32 ? ` (${w / d}:${hh / d})` : ` (${(w / hh).toFixed(2)})`);
  };
  const commit = () => { vals().rect = clamp(vals().rect); draw(); onChange(); };
  const fit = (r, anchor) => {                               // impose le format en gardant le coin opposé
    if (!ratio) return r;
    let [x, y, w, hh] = r;
    if (w / hh > ratio) w = hh * ratio; else hh = w / ratio;
    if (anchor && anchor.includes("w")) x = r[0] + r[2] - w;
    if (anchor && anchor.includes("n")) y = r[1] + r[3] - hh;
    return [x, y, w, hh];
  };
  let drag = null;
  const pos = (e) => { const b = img.getBoundingClientRect(); return [(e.clientX - b.left) / k(), (e.clientY - b.top) / k()]; };
  stage.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const p = pos(e), hd = e.target.dataset.h;
    if (hd) drag = { mode: "resize", hd, p0: p, r0: [...vals().rect] };
    else if (e.target === box) drag = { mode: "move", p0: p, r0: [...vals().rect] };
    else drag = { mode: "new", p0: p };
  });
  if (S.cropCleanup) S.cropCleanup();          // un seul jeu d'écouteurs, même après plusieurs affichages
  const onMove = (e) => {
    if (!drag || !document.body.contains(stage)) return;
    const [px, py] = pos(e), [x0, y0] = drag.p0, dx = px - x0, dy = py - y0;
    if (drag.mode === "move") { const r = drag.r0; vals().rect = clamp([r[0] + dx, r[1] + dy, r[2], r[3]]); }
    else if (drag.mode === "new") {
      let r = [Math.min(x0, px), Math.min(y0, py), Math.abs(dx), Math.abs(dy)];
      vals().rect = fit(r, (px < x0 ? "w" : "") + (py < y0 ? "n" : ""));
    } else {
      let [x, y, w, hh] = drag.r0, hd = drag.hd;
      if (hd.includes("e")) w += dx;
      if (hd.includes("s")) hh += dy;
      if (hd.includes("w")) { x += dx; w -= dx; }
      if (hd.includes("n")) { y += dy; hh -= dy; }
      if (ratio && (hd === "n" || hd === "s")) w = hh * ratio;
      if (ratio && (hd === "e" || hd === "w")) hh = w / ratio;
      vals().rect = fit([x, y, Math.max(16, w), Math.max(16, hh)], hd);
    }
    draw();
  };
  const onUp = () => { if (drag && document.body.contains(stage)) { drag = null; commit(); } };
  const onResize = () => document.body.contains(stage) && draw();
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
  window.addEventListener("resize", onResize);
  S.cropCleanup = () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); window.removeEventListener("resize", onResize); };
  img.onload = draw;
  const ratioSel = h("select", { onchange: (e) => { ratio = S.cropRatio = parseFloat(e.target.value); if (ratio) { vals().rect = fit(vals().rect); } commit(); } },
    RATIOS.map(([l, v]) => h("option", { value: v, selected: v === ratio }, l)));
  const tabs = list.length > 1 ? h("div", { class: "seg" }, list.map((_, i) => h("button", { class: i === S.cropIdx ? "on" : "", onclick: () => { S.cropIdx = i; renderMain(); } }, "Variante " + LETTERS[i]))) : null;
  wrap.append(h("div", { class: "ctools" }, tabs, h("label", { class: "muted" }, "Format "), ratioSel,
    h("button", { class: "ghost small", onclick: () => { vals().rect = [...(step.dyn?.rect || [0, 0, W, H])]; commit(); } }, "Bords seulement (proposé)"),
    h("button", { class: "ghost small", onclick: () => { vals().rect = [0, 0, W, H]; commit(); } }, "Tout le champ"),
    h("span", { class: "spacer" }), size), stage);
  return wrap;
}
