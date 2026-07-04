/* settings-cards.js — Settings card builders. Free build: Piper voices only.
 * Exports: buildLanguageCard, buildDiagCard. */
"use strict";

import { U, API, t, toast, fail, confirmDialog } from "./app-core.js";

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
  var opts = [{ value: "", label: t("settings.lang.auto") }];
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
    text: t("settings.lang.tray_hint"),
  });

  langSel.addEventListener("change", function () {
    var tag = langSel.value; // "" = Auto
    API.call("save_config", { language: tag })
      .then(function (r) {
        if (r && r.ok) {
          toast(t("settings.lang.saved"));
        } else {
          fail(
            new Error(r && r.error ? r.error : t("settings.lang.set_failed")),
          );
        }
      })
      .catch(fail);
  });

  return U.card(t("settings.lang.title"), [
    U.fieldRow(t("settings.lang.label"), langSel),
    trayHint,
  ]);
}

// ------------------------------------------------------------------
// Diagnostics card (local logs only — no upload path).
// ------------------------------------------------------------------
export function buildDiagCard(state) {
  state = state || {};

  // 1. Log-level select: Off / Errors only / Full trace -> set_diag_level.
  var levelSel = U.select(
    "settings-diag-level",
    [
      { value: "off", label: t("settings.diag.level.off") },
      { value: "error", label: t("settings.diag.level.error") },
      { value: "trace", label: t("settings.diag.level.trace") },
    ],
    state.level || "off",
  );
  levelSel.classList.add("grow");

  // 2. Privacy description — no upload path.
  var noticeEl = U.el("div", {
    class: "card-hint",
    testid: "settings-diag-notice",
    html: t("settings.diag.notice"),
  });

  // 3. Status line: log count / KB / folder path -> get_diag_state.
  function statusText(s) {
    var kb = Math.round((s.total_bytes || 0) / 1024);
    return t("settings.diag.status", {
      count: s.log_count || 0,
      kb: kb,
      folder: s.folder || t("settings.diag.folder_default"),
    });
  }
  var statusEl = U.el("div", {
    class: "card-hint",
    testid: "settings-diag-status",
    text: statusText(state),
  });

  function refreshStatus() {
    API.call("get_diag_state")
      .then(function (s) {
        statusEl.textContent = statusText(s);
        levelSel.value = s.level || "off";
      })
      .catch(function () {});
  }

  // 4. Buttons: Open log folder + Delete logs (danger).
  var openBtn = U.el("button", {
    testid: "settings-diag-open",
    text: t("settings.diag.open"),
  });
  var deleteBtn = U.el("button", {
    class: "danger",
    testid: "settings-diag-delete",
    text: t("settings.diag.delete"),
  });

  levelSel.addEventListener("change", function () {
    var lvl = levelSel.value;
    API.call("set_diag_level", lvl)
      .then(function (r) {
        if (r && r.ok) {
          toast(t("settings.diag.level_set", { level: lvl }));
          refreshStatus();
        } else {
          fail(
            new Error(
              r && r.error ? r.error : t("settings.diag.set_level_failed"),
            ),
          );
        }
      })
      .catch(fail);
  });

  openBtn.addEventListener("click", function () {
    API.call("open_diag_folder")
      .then(function (r) {
        if (r && !r.handled && state.folder)
          toast(t("settings.diag.folder_toast", { folder: state.folder }));
      })
      .catch(fail);
  });

  deleteBtn.addEventListener("click", function () {
    confirmDialog(
      t("settings.diag.confirm_title"),
      t("settings.diag.confirm_body"),
    ).then(function (ok) {
      if (!ok) return;
      API.call("delete_diag_logs")
        .then(function (r) {
          if (r && r.ok) {
            toast(t("settings.diag.deleted", { count: r.removed || 0 }));
          } else {
            fail(
              new Error(
                r && r.error ? r.error : t("settings.diag.delete_failed"),
              ),
            );
          }
          refreshStatus();
        })
        .catch(fail);
    });
  });

  return U.card(t("settings.diag.title"), [
    U.fieldRow(t("settings.diag.level_label"), levelSel),
    noticeEl,
    statusEl,
    U.el("div", { class: "row", style: "margin-top:8px" }, [
      openBtn,
      deleteBtn,
    ]),
  ]);
}
