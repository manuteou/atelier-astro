// Fenêtre « NOTES ».
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";

export async function dlgNotes() {
  if (!S.project) return;
  const n = await api("GET", `/api/projects/${S.project}/notes`);
  openDlg("NOTES.md", h("div", { class: "notes" }, n.text));
}
