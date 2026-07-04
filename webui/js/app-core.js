/* app-core.js — shared singletons + helpers for PipPal's web-UI
 * module graph. Refactored from the original app.js IIFE header
 * (the cross-cluster bootstrap + shared helpers). Behavior-preserving:
 * every feature module imports the SAME singleton instances these
 * exports provide, exactly as the monolith's closure shared them.
 *
 * api.js (window.PipPalAPI) and components.js (window.UI) are still
 * loaded as classic scripts BEFORE this module graph, so the two
 * globals are present when this module evaluates. We read them once
 * here and re-export so feature modules import them from one seam.
 *
 * The two window.__pippal* assignments and the CustomEvent/localStorage
 * voice-change signaling STAY on window so other surface windows + the
 * E2E suite see them identically. */
"use strict";

export var U = window.UI;
export var API = window.PipPalAPI;
// i18n translate helper (T-101 engine, defined by the blocking classic
// js/i18n.js in <head> before this module graph evaluates). Re-exported
// from the single app-core seam so every surface module calls the same
// window.t(key, params) contract. window.t is stable (never reassigned),
// so capturing the reference here is safe.
export var t = window.t;
export var view = document.getElementById("view");
export var footer = document.getElementById("footer");
var toastEl = document.getElementById("toast");

// Shared settings state — mutated by renderSettings (settings.js) and read
// by the build*Card builders (settings-cards.js). A single shared singleton
// here (per SPEC §6 shared-state list) gives every settings module the SAME
// instance the monolith's closure provided, and avoids an import cycle
// between settings.js and settings-cards.js.
export var settingsState = {
  config: {},
  defaults: {},
  controls: {},
};

var params = new URLSearchParams(location.search);
export var SURFACE = params.get("view") || "settings";
export var INSTALLED_VOICES_CHANGED_EVENT = "pippal-installed-voices-changed";
export var INSTALLED_VOICES_CHANGED_KEY = "pippal:installed-voices-changed";

export function toast(msg, isErr) {
  toastEl.textContent = msg;
  toastEl.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(function () {
    toastEl.className = "toast";
  }, 2600);
}
window.__pippalToast = toast;

export function fail(e) {
  toast(String((e && e.message) || e), true);
}

export function handleCloseWindowFailure(context, e, fallback) {
  console.warn(context, e);
  fail(e);
  if (typeof fallback === "function") {
    return fallback();
  }
  return Promise.resolve();
}

export function signalInstalledVoicesChanged() {
  var stamp = String(Date.now());
  try {
    localStorage.setItem(INSTALLED_VOICES_CHANGED_KEY, stamp);
  } catch (e) {
    if (window.console && console.warn) {
      console.warn("Could not notify other windows about voice changes.", e);
    }
  }
  try {
    window.dispatchEvent(
      new CustomEvent(INSTALLED_VOICES_CHANGED_EVENT, {
        detail: { stamp: stamp },
      }),
    );
  } catch (e) {
    if (window.console && console.warn) {
      console.warn("Could not notify this window about voice changes.", e);
    }
  }
}

// Real modal confirm gate — the web analogue of Tk's
// messagebox.askyesno (matching the core frontend behavior).
var confirmModal = document.getElementById("confirm-modal");
var confirmTitle = document.getElementById("confirm-title");
var confirmBody = document.getElementById("confirm-body");
var confirmOk = document.getElementById("confirm-ok");
var confirmCancel = document.getElementById("confirm-cancel");
export function confirmDialog(title, body) {
  return new Promise(function (resolve) {
    confirmTitle.textContent = title;
    confirmBody.textContent = body;
    confirmModal.classList.remove("hidden");
    function cleanup(result) {
      confirmModal.classList.add("hidden");
      confirmOk.removeEventListener("click", onOk);
      confirmCancel.removeEventListener("click", onCancel);
      resolve(result);
    }
    function onOk() {
      cleanup(true);
    }
    function onCancel() {
      cleanup(false);
    }
    confirmOk.addEventListener("click", onOk);
    confirmCancel.addEventListener("click", onCancel);
  });
}
window.__pippalConfirm = confirmDialog;

document
  .getElementById("btn-window-close")
  .addEventListener("click", function () {
    API.call("close_window").catch(function (e) {
      return handleCloseWindowFailure(t("errors.close_window"), e);
    });
  });
