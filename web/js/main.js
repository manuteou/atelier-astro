// Point d'entrée de l'interface (modules ES, aucune compilation).
import * as core from "./core.js";
import * as projet from "./projet.js";
import * as page from "./page.js";
import { initViewerEvents } from "./visionneuse.js";

// accès depuis la console du navigateur et les tests automatiques
window.atelier = { ...core, ...projet, ...page };
Object.assign(window, { S: core.S, openProject: projet.openProject, renderSteps: projet.renderSteps,
  renderMain: page.renderMain, closeDlg: core.closeDlg });

initViewerEvents();
projet.init().catch(e => core.toast(e.message, true));
