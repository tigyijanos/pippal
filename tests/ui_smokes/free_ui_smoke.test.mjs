#!/usr/bin/env node
/**
 * Free-edition smoke tests — regression guards for the three surface bugs
 * that were fixed by porting overlay.js, voices.js, and app-core.js into
 * the free module graph.
 *
 * Bug 1: Voice Remove/delete did NOT work in free.
 * Bug 2: Download progress bar was wrong/stuck.
 * Bug 3: Karaoke overlay was an empty black window.
 *
 * Run: node tests/ui_smokes/free_ui_smoke.test.mjs
 *
 * Reads the module-graph source files (voices.js, overlay.js, settings*.js,
 * app-core.js) instead of the old monolithic app.js.
 */

import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const root = join(__dirname, "../..");

function read(rel) {
  return readFileSync(join(root, rel), "utf8");
}

let passed = 0,
  failed = 0;
function assert(condition, label) {
  if (condition) {
    console.log(`PASS: ${label}`);
    passed++;
  } else {
    console.error(`FAIL: ${label}`);
    failed++;
  }
}

// Read individual module files (module-graph replaces the old app.js).
const settingsSrc =
  read("webui/js/settings-cards.js") + "\n" + read("webui/js/settings.js");
const voicesSrc = read("webui/js/voices.js");
const overlaySrc = read("webui/js/overlay.js");
const appCoreSrc = read("webui/js/app-core.js");
// overlay.css was merged into surfaces.css + theme.css (position:fixed lives
// in theme.css; animations live in surfaces.css).
const surfacesCss = read("webui/css/surfaces.css");
const themeCss = read("webui/css/theme.css");

// (a) Regression guard: diag card still present
assert(/function buildDiagCard/.test(settingsSrc), "(a) buildDiagCard defined");
assert(
  settingsSrc.includes("settings-diag-level"),
  "(a) settings-diag-level present",
);
assert(
  /buildDiagCard\s*\(/.test(settingsSrc),
  "(a) buildDiagCard called in renderSettings",
);
assert(
  settingsSrc.includes('"get_diag_state"'),
  "(a) get_diag_state bridge call present",
);

// (b) Voice manager: Remove/delete path is wired
assert(
  appCoreSrc.includes("function signalInstalledVoicesChanged"),
  "(b) signalInstalledVoicesChanged defined in app-core.js",
);
assert(
  appCoreSrc.includes("INSTALLED_VOICES_CHANGED_EVENT"),
  "(b) INSTALLED_VOICES_CHANGED_EVENT present",
);

const doRemoveIdx = voicesSrc.indexOf("function doRemove");
const doInstallIdx = voicesSrc.indexOf("function doInstall");
const doRemoveBlock = voicesSrc.slice(doRemoveIdx, doInstallIdx);
assert(
  doRemoveBlock.includes("signalInstalledVoicesChanged"),
  "(b) doRemove() calls signalInstalledVoicesChanged — Remove wired",
);
assert(
  doRemoveBlock.includes('"get_voice_catalogue"'),
  "(b) doRemove() re-fetches catalogue",
);
assert(
  /testid.*vm-action-/.test(voicesSrc),
  "(b) vm-action-{id} testid present (Remove/Install button)",
);
assert(
  voicesSrc.includes('confirmDialog("Remove voice"'),
  "(b) Remove gated on confirmDialog",
);

// (c) Progress bar: correct CSS classes present in voices.js
assert(
  voicesSrc.includes("install-progress-wrap"),
  "(c) install-progress-wrap in voiceRow JS",
);
assert(
  voicesSrc.includes("install-progress-fill"),
  "(c) install-progress-fill in voiceRow JS",
);
assert(
  voicesSrc.includes("install-progress-bar"),
  "(c) install-progress-bar in voiceRow JS",
);
assert(
  voicesSrc.includes("vm-cancel-"),
  "(c) voiceCancelBtn (vm-cancel-) present",
);
// progress-fill and vm-action-row CSS live in surfaces.css (merged from old files).
assert(
  surfacesCss.includes(".install-progress-fill"),
  "(c) .install-progress-fill CSS in surfaces.css",
);
assert(
  surfacesCss.includes("transition: width"),
  "(c) transition:width in surfaces.css",
);
assert(voicesSrc.includes("vm-action-row"), "(c) vm-action-row in voiceRow JS");
assert(
  surfacesCss.includes(".vm-action-row"),
  "(c) .vm-action-row CSS in surfaces.css",
);

// (d) Overlay: position:fixed + panel structure
// position:fixed for .overlay-panel lives in theme.css (overlay.css was merged).
assert(
  themeCss.includes("position: fixed"),
  "(d) overlay-panel uses position:fixed (empty-black-window fix)",
);
assert(
  overlaySrc.includes('testid: "overlay-panel"'),
  "(d) overlay-panel element created",
);
assert(
  overlaySrc.includes('testid: "overlay-loading"'),
  "(d) overlay-loading sentinel element",
);
assert(
  overlaySrc.includes('testid: "overlay-page-marker"'),
  "(d) overlay-page-marker (counter)",
);
// Transport buttons are created via obtn("prev") etc. — testid is "overlay-" + tag
assert(
  overlaySrc.includes('obtn("prev")'),
  "(d) overlay-prev transport button (obtn call)",
);
assert(
  overlaySrc.includes('obtn("next")'),
  "(d) overlay-next transport button (obtn call)",
);
assert(
  overlaySrc.includes('obtn("pause")'),
  "(d) overlay-pause transport button (obtn call)",
);
assert(
  overlaySrc.includes('testid: "overlay-" + tag'),
  "(d) transport button testid pattern overlay-{tag} present",
);
assert(
  overlaySrc.includes("TICK_FAST_MS"),
  "(d) TICK_FAST_MS idle-aware polling",
);
assert(
  overlaySrc.includes("TICK_SLOW_MS"),
  "(d) TICK_SLOW_MS idle-aware polling",
);
assert(
  overlaySrc.includes("reader-loading-bar"),
  "(d) reader-loading-bar in renderOverlay",
);
// reader-loading-shimmer keyframes live in surfaces.css (merged from overlay.css).
assert(
  surfacesCss.includes("reader-loading-shimmer"),
  "(d) reader-loading-shimmer @keyframes",
);
assert(
  overlaySrc.includes("window.__pippalOverlayKick"),
  "(d) window.__pippalOverlayKick exposed",
);
// (d) #375: CJK karaoke units render with no trailing space so per-character
// Chinese/Japanese segmentation is not visually broken.
assert(
  overlaySrc.includes("CJK_UNIT_RE"),
  "(d) CJK_UNIT_RE trailing-space suppression for CJK karaoke (#375)",
);

// (e) window_lifecycle.py kick wired (overlay re-show path).
let lifecyclePy = "";
try {
  lifecyclePy = read("src/pippal/web_ui/window_lifecycle.py");
} catch (e) {}
assert(
  lifecyclePy.includes("__pippalOverlayKick"),
  "(e) window_lifecycle.py evaluate_js kick wired after overlay show",
);

if (failed > 0) {
  console.error(`\n${failed} of ${passed + failed} test(s) FAILED.`);
  process.exit(1);
} else {
  console.log(`\nAll ${passed} tests passed.`);
  process.exit(0);
}
