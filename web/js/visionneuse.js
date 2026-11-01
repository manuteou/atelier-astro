// Visionneuse plein écran : zoom, zone de zoom, cadre, point.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "./core.js";
import { initEditor } from "./editeur.js";
import { renderMain } from "./page.js";
import { openProject } from "./projet.js";

// ------------------------------------------------------------------ visionneuse
export const V = { mode: "view", step: null, pv: null, drag: null };

export function openViewer(step, pv, title) {
  V.step = step; V.pv = pv; V.mode = "view";
  $("#viewerTitle").textContent = `${step.id} · ${title}`;
  const img = $("#viewerImg");
  img.src = pv.absolute ? pv.main : fileUrl(pv.main);
  $("#sel").className = "sel hidden";
  const inter = !pv.nointeract && pv.size;
  const allowed = { view: true, zoom: inter, crop: inter && (step.interaction === "crop" || step.id === "P8" || step.id === "S4"), point: inter && step.interaction === "point" };
  for (const b of $("#modeSeg").querySelectorAll("button")) {
    b.disabled = !allowed[b.dataset.mode];
    b.classList.toggle("on", b.dataset.mode === "view");
    b.onclick = () => setMode(b.dataset.mode);
  }
  $("#viewer").classList.remove("hidden");
  setMode("view");
}

export function setMode(m) {
  V.mode = m;
  for (const b of $("#modeSeg").querySelectorAll("button")) b.classList.toggle("on", b.dataset.mode === m);
  $("#stage").classList.toggle("crosshair", m !== "view");
  const help = {
    view: "Clique sur « Zone de zoom » pour choisir la zone montrée en détail sous chaque variante.",
    zoom: "Glisse un rectangle : il devient la zone de zoom de toutes les variantes (et des prochaines étapes).",
    crop: V.step.id === "P8" ? "Glisse un rectangle sur un bras externe faible : il devient la zone de contrôle de l'aplanissement."
      : V.step.id === "S4" ? "Glisse un rectangle : il est ajouté aux zones mesurées." : "Glisse le rectangle de cadrage (coordonnées pleine résolution, y depuis le haut).",
    point: V.step.id === "P7" ? "Clique au centre de l'amas à protéger (rayon et nombre se règlent dans la variante)." : "Clique sur le défaut : une ligne « vert x y 25 » est ajoutée (change « vert » en « remplace » pour un anneau d'étoile).",
  }[m];
  $("#viewerHelp").textContent = help;
}

export function closeViewer() { $("#viewer").classList.add("hidden"); }

export function toFull(e) {
  const img = $("#viewerImg");
  const r = img.getBoundingClientRect();
  const k = img.naturalWidth / r.width / (V.pv.scale || 1);
  return [Math.round((e.clientX - r.left) * k), Math.round((e.clientY - r.top) * k)];
}

export function initViewerEvents() {
  const stage = $("#stage"), sel = $("#sel"), img = $("#viewerImg");
  stage.addEventListener("mousemove", (e) => {
    if (!V.pv?.size) return;
    const [x, y] = toFull(e);
    $("#viewerCoords").textContent = `x ${x} · y ${y}`;
    if (V.drag) {
      const r = img.getBoundingClientRect();
      const x0 = Math.min(V.drag[0], e.clientX) - r.left, y0 = Math.min(V.drag[1], e.clientY) - r.top;
      Object.assign(sel.style, { left: x0 + "px", top: y0 + "px", width: Math.abs(e.clientX - V.drag[0]) + "px", height: Math.abs(e.clientY - V.drag[1]) + "px" });
    }
  });
  stage.addEventListener("mousedown", (e) => {
    if (V.mode === "zoom" || V.mode === "crop") {
      e.preventDefault();
      V.drag = [e.clientX, e.clientY, ...toFull(e)];
      sel.className = "sel" + (V.mode === "zoom" ? " zoom" : "");
      Object.assign(sel.style, { width: 0, height: 0 });
    }
  });
  window.addEventListener("mouseup", async (e) => {
    if (!V.drag) return;
    const [, , fx, fy] = V.drag;
    V.drag = null;
    const [x2, y2] = toFull(e);
    const rect = [Math.min(fx, x2), Math.min(fy, y2), Math.abs(x2 - fx), Math.abs(y2 - fy)];
    if (rect[2] < 8 || rect[3] < 8) return;
    if (V.mode === "zoom") {
      await api("POST", `/api/projects/${S.project}/zoom`, { rect, step: S.sid });
      toast("Zone de zoom enregistrée : " + rect.join(" "));
      closeViewer();
      await openProject(S.project, true);
    } else if (V.mode === "crop") {
      const list = S.edit[S.sid] || initEditor(stepById(S.sid));
      if (S.sid === "P8") list.forEach(v => { v.zone = rect.join(","); v.aplanir = true; });
      else if (S.sid === "S4") list.forEach(v => { v.zones = (v.zones ? v.zones + " ; " : "") + `zone${(v.zones || "").split(";").filter(Boolean).length + 1}:${rect.join(",")}`; });
      else list.forEach(v => { v.rect = rect; });
      toast("Rectangle reporté dans les réglages : " + rect.join(" "));
      closeViewer(); renderMain();
    }
  });
  stage.addEventListener("click", (e) => {
    if (V.mode !== "point") return;
    const [x, y] = toFull(e);
    const list = S.edit[S.sid] || initEditor(stepById(S.sid));
    if (S.sid === "P7") list.forEach(v => { const o = (v.amas || "").split(","); v.amas = `${x},${y},${o[2] || 100},${o[3] || 30}`; });
    else list.forEach(v => { v.liste = (v.liste ? v.liste.trim() + "\n" : "") + `vert ${x} ${y} 25`; });
    toast(`Point ${x}, ${y} reporté dans les réglages`);
    renderMain();
  });
}
