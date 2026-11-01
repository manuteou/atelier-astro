// Comparer des variantes : rideau avant/après sur la même image, et zoom synchronisé des cartes de résultats.
import { $, h, LETTERS, S, api, toast, fileUrl, openDlg, stepById } from "./core.js";

// ------------------------------------------------------------- zoom synchronisé des cartes de résultats
// Même transformation pour toutes les images principales des cartes d'une étape : molette = zoom autour du
// pointeur, glisser = se déplacer, double-clic = revenir. d = k * (u + t) : t en fraction de l'image.
function syncState(sid) {
  S.sync = S.sync || {};
  return (S.sync[sid] = S.sync[sid] || { k: 1, x: 0, y: 0 });
}
function applySync(sid) {
  const z = syncState(sid);
  const tr = z.k === 1 ? "" : `scale(${z.k.toFixed(3)}) translate(${(z.x * 100).toFixed(2)}%, ${(z.y * 100).toFixed(2)}%)`;
  document.querySelectorAll(`.thumb-wrap[data-sid="${sid}"] img`).forEach(im => { im.style.transform = tr; });
  document.querySelectorAll(`.zoom-badge[data-sid="${sid}"]`).forEach(b => { b.textContent = z.k === 1 ? "" : `×${z.k.toFixed(1)}`; });
}
const clampT = (t, k) => Math.min(0, Math.max(1 / k - 1, t));

/** Image principale d'une carte, avec zoom synchronisé ; onOpen = clic sans déplacement. */
export function syncImage(sid, src, onOpen) {
  const img = h("img", { class: "rimg", src, draggable: "false" });
  const wrap = h("div", { class: "thumb-wrap", "data-sid": sid, title: "Molette : zoom sur toutes les variantes · glisser : se déplacer · double-clic : revenir · clic : plein écran" },
    img, h("span", { class: "zoom-badge", "data-sid": sid }));
  wrap.addEventListener("wheel", (e) => {
    e.preventDefault();
    const z = syncState(sid), b = wrap.getBoundingClientRect();
    const fx = (e.clientX - b.left) / b.width, fy = (e.clientY - b.top) / b.height;
    const k2 = Math.min(12, Math.max(1, z.k * (e.deltaY < 0 ? 1.3 : 1 / 1.3)));
    const u = fx / z.k - z.x, v = fy / z.k - z.y;
    z.x = clampT(fx / k2 - u, k2); z.y = clampT(fy / k2 - v, k2); z.k = k2;
    applySync(sid);
  }, { passive: false });
  let drag = null;
  wrap.addEventListener("mousedown", (e) => { if (e.button === 0) { e.preventDefault(); const z = syncState(sid); drag = { x: e.clientX, y: e.clientY, tx: z.x, ty: z.y, moved: false }; } });
  window.addEventListener("mousemove", (e) => {
    if (!drag || !document.body.contains(wrap)) return;
    const z = syncState(sid), b = wrap.getBoundingClientRect();
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.hypot(dx, dy) > 3) drag.moved = true;
    if (!drag.moved || z.k === 1) return;
    z.x = clampT(drag.tx + dx / b.width / z.k, z.k); z.y = clampT(drag.ty + dy / b.height / z.k, z.k);
    applySync(sid);
  });
  window.addEventListener("mouseup", () => {
    if (!drag || !document.body.contains(wrap)) { drag = null; return; }
    const d = drag; drag = null;
    if (!d.moved && onOpen) onOpen();
  });
  wrap.addEventListener("dblclick", () => { Object.assign(syncState(sid), { k: 1, x: 0, y: 0 }); applySync(sid); });
  img.addEventListener("load", () => applySync(sid));
  return wrap;
}

// ------------------------------------------------------------- rideau avant / après
/** Images comparables d'une étape : référence, variante retenue, variantes de l'essai. */
export function comparables(step) {
  const out = [];
  if (step.reference) {
    const r = stepById(step.reference);
    const pv = r?.state?.retained?.previews;
    if (pv?.main) out.push({ label: `Réf. · ${r.id} ${r.title}`, pv });
  }
  const st = step.state || {};
  if (st.retained?.previews && st.chosen == null && ["done", "stale"].includes(st.status))
    out.push({ label: "Retenue actuellement", pv: st.retained.previews });
  (st.variants || []).forEach((v, i) => { if (v.previews?.main) out.push({ label: `Variante ${LETTERS[i]}`, pv: v.previews }); });
  return out;
}

export function dlgCompare(step) {
  const list = comparables(step);
  if (list.length < 2) { toast("Il faut au moins deux images (référence ou variantes) pour comparer", true); return; }
  const def = S.cmp?.[step.id] || [list.length > 2 ? list.length - 2 : 0, list.length - 1];
  let [ia, ib] = def.map(i => Math.min(i, list.length - 1));
  const z = { k: 1, x: 0, y: 0 };
  let split = 0.5, full = false;
  const imgA = h("img", { draggable: "false" }), imgB = h("img", { draggable: "false" });
  const layerA = h("div", { class: "cmp-layer cmp-a" }, imgA), layerB = h("div", { class: "cmp-layer" }, imgB);
  const line = h("div", { class: "cmp-line" });
  const labA = h("span", { class: "cmp-lab left" }), labB = h("span", { class: "cmp-lab right" });
  const box = h("div", { class: "cmp-box" }, layerB, layerA, line);
  const stage = h("div", { class: "cmp-stage", "data-split": split, "data-zoom": 1 }, box, labA, labB);
  const fit = () => {                       // boîte aux proportions de l'image, centrée : les fractions s'y rapportent
    const W = stage.clientWidth, H = stage.clientHeight, iw = imgB.naturalWidth || 4, ih = imgB.naturalHeight || 3;
    const k = Math.min(W / iw, H / ih);
    Object.assign(box.style, { width: iw * k + "px", height: ih * k + "px", left: (W - iw * k) / 2 + "px", top: (H - ih * k) / 2 + "px" });
  };
  imgB.addEventListener("load", fit);
  const zoomLbl = h("span", { class: "mono muted" });
  const paint = () => {
    const tr = `scale(${z.k}) translate(${z.x * 100}%, ${z.y * 100}%)`;
    imgA.style.transform = imgB.style.transform = tr;
    layerA.style.clipPath = `inset(0 ${(1 - split) * 100}% 0 0)`;
    line.style.left = split * 100 + "%";
    stage.dataset.split = split.toFixed(3); stage.dataset.zoom = z.k.toFixed(2);
    zoomLbl.textContent = `×${z.k.toFixed(1)}`;
  };
  const srcOf = async (it) => {
    if (!full || !it.pv.source) return fileUrl(it.pv.main);
    const r = await api("GET", `/api/projects/${encodeURIComponent(S.project)}/fullres?src=${encodeURIComponent(it.pv.source)}&linear=${it.pv.linear ? 1 : 0}`);
    return fileUrl(r.image);
  };
  const load = async () => {
    S.cmp = { ...(S.cmp || {}), [step.id]: [ia, ib] };
    labA.textContent = "◀ " + list[ia].label; labB.textContent = list[ib].label + " ▶";
    status.textContent = full ? "chargement en pleine résolution…" : "";
    try { [imgA.src, imgB.src] = await Promise.all([srcOf(list[ia]), srcOf(list[ib])]); status.textContent = ""; }
    catch (e) { status.textContent = e.message; }
    paint();
  };
  const sel = (v, set) => h("select", { onchange: (e) => { set(parseInt(e.target.value)); load(); } }, list.map((it, i) => h("option", { value: i, selected: i === v }, it.label)));
  const status = h("span", { class: "muted small" });
  // souris : glisser à gauche = rideau ; clic droit / molette enfoncée = se déplacer ; molette = zoom
  let drag = null;
  const frac = (e) => { const b = box.getBoundingClientRect(); return [(e.clientX - b.left) / b.width, (e.clientY - b.top) / b.height]; };
  stage.addEventListener("contextmenu", (e) => e.preventDefault());
  stage.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const [fx, fy] = frac(e);
    if (e.button === 0) { split = Math.min(1, Math.max(0, fx)); paint(); drag = { curtain: true }; }
    else drag = { pan: true, fx, fy, x: z.x, y: z.y };
  });
  const move = (e) => {
    if (!drag || !document.body.contains(stage)) return;
    const [fx, fy] = frac(e);
    if (drag.curtain) split = Math.min(1, Math.max(0, fx));
    else { z.x = clampT(drag.x + (fx - drag.fx) / z.k, z.k); z.y = clampT(drag.y + (fy - drag.fy) / z.k, z.k); }
    paint();
  };
  const up = () => { drag = null; };
  window.addEventListener("mousemove", move);
  window.addEventListener("mouseup", up);
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [fx, fy] = frac(e);
    const k2 = Math.min(16, Math.max(1, z.k * (e.deltaY < 0 ? 1.3 : 1 / 1.3)));
    const u = fx / z.k - z.x, v = fy / z.k - z.y;
    z.x = clampT(fx / k2 - u, k2); z.y = clampT(fy / k2 - v, k2); z.k = k2;
    paint();
  }, { passive: false });
  stage.addEventListener("dblclick", () => { Object.assign(z, { k: 1, x: 0, y: 0 }); paint(); });
  const fullBox = h("input", { type: "checkbox", onchange: (e) => { full = e.target.checked; load(); } });
  const body = h("div", { class: "cmp" },
    h("div", { class: "ctools" }, h("label", { class: "muted" }, "Gauche "), sel(ia, v => { ia = v; }),
      h("button", { class: "ghost small", title: "Échanger", onclick: () => { [ia, ib] = [ib, ia]; body.replaceWith(dlgCompareBody()); } }, "⇄"),
      h("label", { class: "muted" }, " Droite "), sel(ib, v => { ib = v; }),
      h("label", { class: "muted", style: "margin-left:10px" }, fullBox, " pleine résolution"),
      h("span", { class: "spacer" }), zoomLbl, status),
    stage,
    h("div", { class: "hint" }, "Glisser (clic gauche) : déplacer le rideau · molette : zoom identique des deux côtés · clic droit glissé : se déplacer · double-clic : revenir."));
  const dlgCompareBody = () => { S.cmp[step.id] = [ia, ib]; setTimeout(() => dlgCompare(step)); return h("div"); };
  openDlg(`Comparer · ${step.id} ${step.title}`, body);
  $("#dlg .dialog").classList.add("wide");
  const prevClose = $("#dlgClose").onclick;
  $("#dlgClose").onclick = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); $("#dlg .dialog").classList.remove("wide"); prevClose && prevClose(); };
  window.addEventListener("resize", fit);
  load();
}
