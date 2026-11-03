// Fenêtre « Réglages » : chemins, outils de traitement, Ollama.
import { $, h, LETTERS, STATUS, S, api, toast, fileUrl, toggleConsole, stepById, openDlg, closeDlg, fmtSize } from "../core.js";
import { loadConfig, loadProjects } from "../projet.js";

export async function dlgSettings() {
  const c = (await api("GET", "/api/config")).config;
  const keys = [["astro_root", "Dossier des sessions et projets"], ["dossier_finaux", "Dossier des travaux terminés (vide : FINAUX TRAITES dans la racine s'il existe)"], ["siril_cli", "Chemin de siril-cli"], ["script_graxpert", "Script GraXpert"], ["script_bxt", "Script BlurXTerminator"],
    ["script_nxt", "Script NoiseXTerminator"], ["script_starx", "Script StarXTerminator"], ["script_statstretch", "Script Statistical Stretch"]];
  const ins = {};
  const body = h("div", {});
  for (const [k, l] of keys) { ins[k] = h("input", { type: "text", value: c[k] ?? "" }); body.append(h("div", { class: "field" }, h("label", {}, l), ins[k])); }
  ins.crop_y_origin = h("select", {}, ["haut", "bas"].map(v => h("option", { value: v, selected: c.crop_y_origin === v }, v)));
  ins.select_index_base = h("select", {}, [1, 0].map(v => h("option", { value: v, selected: c.select_index_base == v }, String(v))));
  ins.spcc_catalog_local = h("input", { type: "checkbox", checked: !!c.spcc_catalog_local });
  const ot = await api("GET", "/api/outils");
  const toolSel = {}, toolPerso = {};
  const toolBox = h("div", {});
  for (const [k, f] of Object.entries(ot.fonctions)) {
    toolPerso[k] = h("textarea", { placeholder: "ex. pyscript \"MonScript.py\" -force {force}   (une commande Siril par ligne ; {force} = réglage de l'étape)", style: "min-height:48px" }, ot.perso[k] || "");
    const persoField = h("div", { class: "field", style: "margin:-4px 0 8px 12px" }, toolPerso[k]);
    toolSel[k] = h("select", { onchange: () => { persoField.style.display = toolSel[k].value === "perso" ? "" : "none"; } },
      f.choix.map(([v, l]) => h("option", { value: v, selected: ot.choix[k] === v }, l)));
    persoField.style.display = ot.choix[k] === "perso" ? "" : "none";
    toolBox.append(h("div", { class: "field" }, h("label", {}, f.label), toolSel[k]), persoField);
  }
  const ol = await api("GET", "/api/ollama").catch(() => ({ ok: false, models: [] }));
  ins.ollama_url = h("input", { type: "text", value: c.ollama_url || "" });
  ins.ollama_model = h("select", {}, h("option", { value: "" }, ol.ok ? "(premier modèle installé)" : "(Ollama non détecté)"),
    ol.models.map(m => h("option", { value: m, selected: c.ollama_model === m }, m)));
  body.append(h("h3", {}, "Outils de traitement"),
    h("p", { class: "hint" }, "Pour chaque fonction : RC Astro, GraXpert, les outils intégrés à Siril, une commande Siril personnalisée (script d'un autre outil), ou aucun (l'étape est alors sans objet). Les scripts RC Astro et GraXpert se règlent plus haut."),
    toolBox);
  body.append(h("div", { class: "field" }, h("label", {}, "Siril : y du crop compté depuis (détecté automatiquement au premier recadrage asymétrique)"), ins.crop_y_origin));
  body.append(h("div", { class: "field" }, h("label", {}, "Numérotation de select/unselect (contrôlée par STACKCNT en mode B)"), ins.select_index_base));
  body.append(h("div", { class: "field check" }, h("label", {}, ins.spcc_catalog_local, "Catalogue Gaia local installé dans Siril (SPCC)")));
  body.append(h("h3", {}, "Avis local (Ollama, facultatif)"),
    h("div", { class: "field" }, h("label", {}, "Adresse d'Ollama"), ins.ollama_url),
    h("div", { class: "field" }, h("label", {}, "Modèle" + (ol.ok ? ` (${ol.models.length} installé(s))` : " — Ollama non joignable")), ins.ollama_model));
  body.append(h("div", { class: "actions" }, h("button", {
    onclick: async () => {
      const data = {};
      for (const [k] of keys) data[k] = ins[k].value.trim();
      data.crop_y_origin = ins.crop_y_origin.value;
      data.select_index_base = parseInt(ins.select_index_base.value);
      data.spcc_catalog_local = ins.spcc_catalog_local.checked;
      data.ollama_url = ins.ollama_url.value.trim();
      data.ollama_model = ins.ollama_model.value;
      data.outils = Object.fromEntries(Object.keys(toolSel).map(k => [k, toolSel[k].value]));
      data.outils_perso = Object.fromEntries(Object.keys(toolPerso).map(k => [k, toolPerso[k].value]));
      await api("POST", "/api/config", data);
      closeDlg(); await loadConfig();
      S.ollama = await api("GET", "/api/ollama").catch(() => ({ ok: false, models: [] }));
      await loadProjects(S.project);
      toast("Réglages enregistrés");
    }
  }, "Enregistrer")));
  openDlg("Réglages", body);
}
