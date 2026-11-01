// P11 : éditeur de retouches locales (cercles, zoom, déplacement de la vue).
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";
import { initEditor } from "../editeur.js";
import { loadImg, pixels } from "../etapes/reglage_fin.js";
import { setMode } from "../visionneuse.js";

// ------------------------------------------------------------------ retouches locales (P11)
// Aperçu immédiat qui reproduit app/scripts/retouche_locale.py (disque adouci sur 40 % du rayon).
export const RET_LABEL = { vert: "Point vert", remplace: "Anneau d'étoile" };

export function parseRetouches(txt) {
  return (txt || "").split("\n").map(l => l.trim().split(/\s+/)).filter(a => a.length >= 4 && (a[0] === "vert" || a[0] === "remplace"))
    .map(a => ({ mode: a[0], x: Math.round(+a[1]), y: Math.round(+a[2]), r: Math.round(+a[3]) }));
}

export function retoucher(step) {
  const vals = initEditor(step)[0];
  let items = parseRetouches(vals.liste);
  let sel = -1, tool = S.retTool || "vert", rad = S.retRad || 25, before = false;
  let src = null, view = { k: 1, x: 0, y: 0, mode: "cercle" };
  const canvas = h("canvas", { class: "ret-canvas" });
  const work = document.createElement("canvas");
  const status = h("div", { class: "muted small" }, "chargement de l'image pleine résolution…");
  const listBox = h("div", { class: "ret-list" });
  const sync = () => {
    vals.liste = items.map(it => `${it.mode} ${it.x} ${it.y} ${it.r}`).join("\n");
    const b = $("#btnRun"); if (b) { b.disabled = !items.length || !!S.job; b.title = items.length ? "" : "Clique d'abord sur un défaut dans l'image"; }
  };
  const apply = () => {                         // image corrigée en pleine résolution, dans un canevas caché
    if (!src) return;
    const out = new Uint8ClampedArray(src.cur);
    if (!before) for (const it of items) {
      const r = Math.max(it.r, 1), soft = Math.max(0.4 * r, 1);
      const x0 = Math.max(0, Math.floor(it.x - r)), x1 = Math.min(src.w - 1, Math.ceil(it.x + r));
      const y0 = Math.max(0, Math.floor(it.y - r)), y1 = Math.min(src.h - 1, Math.ceil(it.y + r));
      for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
        const m = Math.min(1, Math.max(0, (r - Math.hypot(x - it.x, y - it.y)) / soft));
        if (!m) continue;
        const i = (y * src.w + x) * 4;
        if (it.mode === "vert") { const g = Math.min(out[i + 1], Math.max(out[i], out[i + 2])); out[i + 1] = out[i + 1] * (1 - m) + g * m; }
        else if (src.nat) for (let c = 0; c < 3; c++) out[i + c] = out[i + c] * (1 - m) + src.nat[i + c] * m;
      }
    }
    work.getContext("2d").putImageData(new ImageData(out, src.w, src.h), 0, 0);
    paint();
  };
  const paint = () => {
    if (!src) return;
    const cw = canvas.clientWidth, ch = canvas.clientHeight, dpr = window.devicePixelRatio || 1;
    if (canvas.width !== cw * dpr) { canvas.width = cw * dpr; canvas.height = ch * dpr; }
    const g = canvas.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = "#000"; g.fillRect(0, 0, cw, ch);
    g.imageSmoothingEnabled = view.k < 2;
    g.drawImage(work, view.x, view.y, src.w * view.k, src.h * view.k);
    items.forEach((it, i) => {
      const cx = view.x + it.x * view.k, cy = view.y + it.y * view.k, cr = Math.max(it.r * view.k, 4);
      g.lineWidth = i === sel ? 2.5 : 1.5;
      g.strokeStyle = it.mode === "vert" ? "#4ade80" : "#fb923c";
      g.setLineDash(i === sel ? [] : [5, 4]);
      g.beginPath(); g.arc(cx, cy, cr, 0, 2 * Math.PI); g.stroke();
      g.setLineDash([]); g.fillStyle = g.strokeStyle; g.font = "bold 12px sans-serif";
      g.fillText(String(i + 1), cx + cr * 0.72 + 3, cy - cr * 0.72 - 3);
    });
    zoomLbl.textContent = Math.round(view.k * 100) + " %";
  };
  const fit = () => {
    if (!src) return;
    const cw = canvas.clientWidth, ch = canvas.clientHeight;
    view.k = Math.min(cw / src.w, ch / src.h); view.x = (cw - src.w * view.k) / 2; view.y = (ch - src.h * view.k) / 2; paint();
  };
  const zoomAt = (k, cx, cy) => {
    k = Math.min(8, Math.max(0.05, k));
    view.x = cx - (cx - view.x) * k / view.k; view.y = cy - (cy - view.y) * k / view.k; view.k = k; paint();
  };
  const center = (it, k) => { const cw = canvas.clientWidth, ch = canvas.clientHeight; view.k = k || Math.max(view.k, 1); view.x = cw / 2 - it.x * view.k; view.y = ch / 2 - it.y * view.k; paint(); };
  const toImg = (e) => { const b = canvas.getBoundingClientRect(); return [(e.clientX - b.left - view.x) / view.k, (e.clientY - b.top - view.y) / view.k, e.clientX - b.left, e.clientY - b.top]; };
  const hit = (ix, iy) => { let best = -1, bd = Infinity; items.forEach((it, i) => { const d = Math.hypot(it.x - ix, it.y - iy); if (d <= Math.max(it.r, 8 / view.k) && d < bd) { bd = d; best = i; } }); return best; };
  const changed = () => { sync(); drawList(); apply(); };

  let drag = null;
  // Clic gauche = cercle (ou attraper un cercle existant pour le déplacer). Déplacer la vue : outil « Déplacer la vue »,
  // ou glisser avec le clic droit / la molette enfoncée, ou en maintenant la barre d'espace. Un clic n'est jamais
  // pris pour un déplacement de la vue (avant : un clic qui bougeait de quelques pixels déplaçait l'image).
  let space = false;
  const panning = (e) => view.mode === "pan" || space || e.button === 1 || e.button === 2;
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("mousedown", (e) => {
    e.preventDefault(); canvas.focus();
    const [ix, iy, sx, sy] = toImg(e);
    if (panning(e)) { drag = { pan: true, sx, sy, vx: view.x, vy: view.y }; canvas.style.cursor = "grabbing"; return; }
    if (e.button !== 0) return;
    const i = hit(ix, iy);
    drag = { pan: false, sx, sy, item: i, moved: false, ix, iy, ox: i >= 0 ? items[i].x - ix : 0, oy: i >= 0 ? items[i].y - iy : 0 };
  });
  const onMove = (e) => {
    if (!document.body.contains(canvas)) return;
    const [ix, iy, sx, sy] = toImg(e);
    if (!drag) {
      if (e.target === canvas) canvas.style.cursor = (view.mode === "pan" || space) ? "grab" : hit(ix, iy) >= 0 ? "move" : "crosshair";
      return;
    }
    if (drag.pan) { view.x = drag.vx + sx - drag.sx; view.y = drag.vy + sy - drag.sy; paint(); return; }
    if (drag.item >= 0 && Math.hypot(sx - drag.sx, sy - drag.sy) > 3) {
      drag.moved = true;
      const it = items[drag.item]; it.x = Math.round(ix + drag.ox); it.y = Math.round(iy + drag.oy); sel = drag.item; paint();
    }
  };
  const onUp = () => {
    if (!drag || !document.body.contains(canvas)) { drag = null; return; }
    const d = drag; drag = null;
    if (d.pan) { canvas.style.cursor = view.mode === "pan" ? "grab" : "crosshair"; return; }
    if (d.item >= 0) { sel = d.item; if (d.moved) changed(); else { drawList(); paint(); } return; }
    if (!src || d.ix < 0 || d.iy < 0 || d.ix >= src.w || d.iy >= src.h) return;
    items.push({ mode: tool, x: Math.round(d.ix), y: Math.round(d.iy), r: rad }); sel = items.length - 1; changed();
  };
  const onKey = (e) => {
    if (!document.body.contains(canvas)) return;
    if (e.code === "Space" && document.activeElement === canvas) { space = e.type === "keydown"; e.preventDefault(); canvas.style.cursor = space ? "grab" : "crosshair"; }
  };
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
  window.addEventListener("keydown", onKey);
  window.addEventListener("keyup", onKey);
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [, , sx, sy] = toImg(e);
    if (e.shiftKey && sel >= 0) { items[sel].r = Math.max(3, Math.min(300, items[sel].r + (e.deltaY < 0 ? 2 : -2))); rad = S.retRad = items[sel].r; radIn.value = rad; radOut.textContent = rad + " px"; changed(); return; }
    zoomAt(view.k * (e.deltaY < 0 ? 1.25 : 0.8), sx, sy);
  }, { passive: false });
  canvas.tabIndex = 0;
  canvas.addEventListener("keydown", (e) => { if ((e.key === "Delete" || e.key === "Backspace") && sel >= 0) { items.splice(sel, 1); sel = -1; changed(); e.preventDefault(); } });

  const drawList = () => {
    listBox.innerHTML = "";
    if (!items.length) { listBox.append(h("div", { class: "muted small" }, "Aucune retouche. Si tu ne vois aucun défaut, « Passer l'étape »." )); return; }
    items.forEach((it, i) => {
      const r = h("input", { type: "number", min: 3, max: 300, value: it.r, title: "rayon (px)", onchange: e => { it.r = Math.max(3, parseInt(e.target.value) || it.r); changed(); } });
      const m = h("select", { onchange: e => { it.mode = e.target.value; changed(); } }, Object.entries(RET_LABEL).map(([v, l]) => h("option", { value: v, selected: v === it.mode }, l)));
      listBox.append(h("div", { class: "ret-item" + (i === sel ? " on" : ""), onclick: (e) => { if (e.target.tagName === "DIV" || e.target.tagName === "B" || e.target.tagName === "SPAN") { sel = i; center(it, Math.max(view.k, 1.5)); drawList(); } } },
        h("b", { class: it.mode }, String(i + 1)), m, r, h("span", { class: "muted mono" }, `${it.x}, ${it.y}`),
        h("button", { class: "ghost small", title: "Supprimer", onclick: (e) => { e.stopPropagation(); items.splice(i, 1); sel = -1; changed(); } }, "✕")));
    });
  };

  const tools = h("div", { class: "seg" }, Object.entries(RET_LABEL).map(([v, l]) =>
    h("button", { class: tool === v ? "on" : "", "data-tool": v, onclick: (e) => { tool = S.retTool = v; tools.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.tool === v)); } }, l)));
  const radOut = h("span", { class: "mono" }, rad + " px");
  const radIn = h("input", { type: "range", min: 3, max: 150, step: 1, value: rad, oninput: e => { rad = S.retRad = parseInt(e.target.value); radOut.textContent = rad + " px"; if (sel >= 0) { items[sel].r = rad; changed(); } } });
  const zoomLbl = h("span", { class: "mono muted" }, "");
  const hold = h("button", { class: "ghost small", title: "Maintenir pour voir l'image sans les retouches",
    onmousedown: () => { before = true; apply(); }, onmouseup: () => { before = false; apply(); }, onmouseleave: () => { if (before) { before = false; apply(); } } }, "Maintenir : avant");
  const text = h("details", { class: "ret-text" }, h("summary", { class: "muted small" }, "Modifier en texte"),
    h("textarea", { oninput: e => { vals.liste = e.target.value; items = parseRetouches(vals.liste); sel = -1; drawList(); apply(); const b = $("#btnRun"); if (b) b.disabled = !items.length || !!S.job; } }, vals.liste || ""));

  const panel = h("div", { class: "ret-panel" },
    h("div", { class: "small" }, h("b", {}, "1. Outil")), tools,
    h("div", { class: "hint" }, "Point vert : enlève le vert en trop dans le cercle. Anneau d'étoile : remplace le cercle par la version naturelle (sans renfort de couleur)."),
    h("div", { class: "small" }, h("b", {}, "2. Taille du cercle")), h("div", { class: "row" }, radIn, radOut),
    h("div", { class: "small" }, h("b", {}, "3. Clique sur le défaut")),
    h("div", { class: "hint" }, "Clic : poser un cercle · glisser un cercle : le déplacer · molette : zoom · déplacer l'image : bouton « Déplacer la vue », ou glisser avec le clic droit, ou en maintenant la barre d'espace · Maj + molette : taille du cercle choisi · Suppr : l'effacer."),
    h("div", { class: "small" }, h("b", {}, "Retouches")), listBox, text, status);
  const modeSeg = h("div", { class: "seg" },
    h("button", { class: "on", "data-m": "cercle", title: "Clic = poser un cercle ; glisser un cercle = le déplacer", onclick: () => setMode("cercle") }, "✚ Poser un cercle"),
    h("button", { "data-m": "pan", title: "Glisser = déplacer l'image (aussi : clic droit ou barre d'espace)", onclick: () => setMode("pan") }, "✋ Déplacer la vue"));
  const setMode = (m) => { view.mode = m; modeSeg.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.m === m)); canvas.style.cursor = m === "pan" ? "grab" : "crosshair"; };
  const bar = h("div", { class: "ctools" }, modeSeg, hold,
    h("button", { class: "ghost small", onclick: fit }, "Image entière"),
    h("button", { class: "ghost small", onclick: () => zoomAt(1, canvas.clientWidth / 2, canvas.clientHeight / 2) }, "100 %"),
    h("button", { class: "ghost small", onclick: () => zoomAt(2, canvas.clientWidth / 2, canvas.clientHeight / 2) }, "200 %"),
    h("span", { class: "spacer" }), zoomLbl);
  const wrap = h("div", { class: "ret" }, h("div", { class: "ret-view" }, bar, canvas), panel);
  drawList(); sync();
  if (S.retCleanup) S.retCleanup();
  const onResize = () => document.body.contains(canvas) && paint();
  window.addEventListener("resize", onResize);
  S.retCleanup = () => { for (const [ev, fn] of [["resize", onResize], ["mousemove", onMove], ["mouseup", onUp], ["keydown", onKey], ["keyup", onKey]]) window.removeEventListener(ev, fn); };
  (async () => {
    try {
      const R = await api("GET", `/api/projects/${S.project}/retouch`);
      const im = await loadImg(fileUrl(R.image));
      const w = im.naturalWidth, hh = im.naturalHeight;
      const nat = R.naturel ? await loadImg(fileUrl(R.naturel)) : null;
      src = { w, h: hh, cur: pixels(im, w, hh), nat: nat ? pixels(nat, w, hh) : null };
      work.width = w; work.height = hh;
      status.textContent = `Image ${w}×${hh} px, pleine résolution.` + (nat ? "" : " Pas de version naturelle : l'outil « Anneau d'étoile » n'aura pas d'effet.");
      requestAnimationFrame(() => { fit(); apply(); });
    } catch (e) { status.textContent = e.message; }
  })();
  return wrap;
}
