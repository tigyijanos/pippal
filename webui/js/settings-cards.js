/* settings-cards.js — Settings card builders. Free build: Piper voices only.
 * Exports: buildLanguageCard, buildDiagCard. */
"use strict";

import { U, API, toast, fail, confirmDialog } from "./app-core.js";

// Minimal translate shim: use the real i18n engine (window.t, T-101) when
// it is present; otherwise render the English literal. The static labels
// carry their design key so T-104's catalog extraction can wire them.
function tt(key, english) {
  return typeof window.t === "function" ? window.t(key, english) : english;
}

// ------------------------------------------------------------------
// Language card (0.3.1 i18n) — Auto (system) + one option per supported
// catalog, each shown in its OWN language. Selecting persists via the
// existing save_config seam (Auto writes ""); a restart hint covers the
// tray, whose menu is built once at startup (design §5.5).
// ------------------------------------------------------------------
export function buildLanguageCard(cfg) {
  cfg = cfg || {};

  // Options are DRIVEN BY the backend's supported-language set
  // (get_config -> supported_languages, itself SUPPORTED_LANGS): adding a
  // catalog file adds an option here with no UI code change.
  var supported = Array.isArray(cfg.supported_languages)
    ? cfg.supported_languages
    : [];
  var opts = [{ value: "", label: tt("settings.lang.auto", "Auto (system)") }];
  supported.forEach(function (l) {
    if (l && l.tag) opts.push({ value: l.tag, label: l.name || l.tag });
  });

  // cfg.language is the RAW stored value ("" = Auto); the concrete tag the
  // UI renders in is cfg.language_resolved.
  var langSel = U.select("settings-language", opts, cfg.language || "");
  langSel.classList.add("grow");

  var trayHint = U.el("div", {
    class: "card-hint",
    testid: "settings-language-hint",
    "data-i18n": "settings.lang.tray_hint",
    text: tt("settings.lang.tray_hint", "Tray menu updates after restart."),
  });

  langSel.addEventListener("change", function () {
    var tag = langSel.value; // "" = Auto
    API.call("save_config", { language: tag }).then(function (r) {
      if (r && r.ok) {
        toast(tt("settings.lang.saved", "Language saved — reload to apply."));
      } else {
        fail(new Error(r && r.error ? r.error : "Failed to set language."));
      }
    }).catch(fail);
  });

  return U.card(tt("settings.lang.title", "Language"), [
    U.fieldRow(tt("settings.lang.label", "Interface language"), langSel),
    trayHint,
  ]);
}

// ------------------------------------------------------------------
// Diagnostics card (local logs only — no upload path).
// ------------------------------------------------------------------
export function buildDiagCard(state) {
  state = state || {};

  // 1. Log-level select: Off / Errors only / Full trace -> set_diag_level.
  var levelSel = U.select("settings-diag-level", [
    { value: "off",   label: "Off" },
    { value: "error", label: "Errors only" },
    { value: "trace", label: "Full trace" },
  ], state.level || "off");
  levelSel.classList.add("grow");

  // 2. Privacy description — no upload path.
  var noticeEl = U.el("div", {
    class: "card-hint",
    testid: "settings-diag-notice",
    html:
      "Diagnostics logs help the creator fix bugs. "
      + "<strong>Your reading text is never logged</strong> — only "
      + "technical metadata (sizes, formats, timings, and error types). "
      + "Logs stay on your computer. "
      + "Off keeps logging disabled; Errors only records failures; "
      + "Full trace records detailed step-by-step events for harder bugs.",
  });

  // 3. Status line: log count / KB / folder path -> get_diag_state.
  function statusText(s) {
    var kb = Math.round((s.total_bytes || 0) / 1024);
    return (s.log_count || 0) + " log file" + (s.log_count === 1 ? "" : "s")
      + "  \xb7  " + kb + " KB"
      + "  \xb7  " + (s.folder || "local PipPal folder");
  }
  var statusEl = U.el("div", {
    class: "card-hint",
    testid: "settings-diag-status",
    text: statusText(state),
  });

  function refreshStatus() {
    API.call("get_diag_state").then(function (s) {
      statusEl.textContent = statusText(s);
      levelSel.value = s.level || "off";
    }).catch(function () {});
  }

  // 4. Buttons: Open log folder + Delete logs (danger).
  var openBtn = U.el("button", {
    testid: "settings-diag-open",
    text: "Open log folder",
  });
  var deleteBtn = U.el("button", {
    class: "danger",
    testid: "settings-diag-delete",
    text: "Delete logs",
  });

  levelSel.addEventListener("change", function () {
    var lvl = levelSel.value;
    API.call("set_diag_level", lvl).then(function (r) {
      if (r && r.ok) {
        toast("Diagnostics level set to “" + lvl + "”.");
        refreshStatus();
      } else {
        fail(new Error(r && r.error ? r.error : "Failed to set level."));
      }
    }).catch(fail);
  });

  openBtn.addEventListener("click", function () {
    API.call("open_diag_folder").then(function (r) {
      if (r && !r.handled && state.folder) toast("Log folder: " + state.folder);
    }).catch(fail);
  });

  deleteBtn.addEventListener("click", function () {
    confirmDialog(
      "Delete diagnostics logs",
      "Delete all diagnostics logs? This cannot be undone.",
    ).then(function (ok) {
      if (!ok) return;
      API.call("delete_diag_logs").then(function (r) {
        if (r && r.ok) {
          toast("Deleted " + (r.removed || 0) + " log file"
            + (r.removed === 1 ? "" : "s") + ".");
        } else {
          fail(new Error(r && r.error ? r.error : "Delete failed."));
        }
        refreshStatus();
      }).catch(fail);
    });
  });

  return U.card("Diagnostics", [
    U.fieldRow("Log level", levelSel),
    noticeEl,
    statusEl,
    U.el("div", { class: "row", style: "margin-top:8px" }, [openBtn, deleteBtn]),
  ]);
}
