/* main.js — PipPal (free) web-UI module entrypoint.
 *
 * Loaded as <script type="module"> from index.html, AFTER the classic
 * api.js / pro_diag_instrument.js / pro_bridge_resilient.js / components.js
 * scripts (which set window.PipPalAPI / window.UI). This file is the
 * single module entry; it imports shared singletons + helpers from
 * app-core.js and the feature-surface renderers from their own modules,
 * then dispatches the ?view= surface.
 *
 * Surfaces in this build: overlay, voices, notices, onboarding, settings.
 * Settings: full ES6-module port (step 5) — settings.js + settings-cards.js +
 *           settings-footer.js. settings-stub.js deleted.
 * Stripped (not in free): moods, release, import, queue, recent. */
"use strict";

import { API, SURFACE, toast, fail } from "./app-core.js";
import { renderSettings } from "./settings.js";
import { wireFooter } from "./settings-footer.js";
import { renderOnboarding } from "./onboarding.js";
import { renderVoiceManager } from "./voices.js";
import { renderNotices } from "./notices.js";
import { renderOverlay } from "./overlay.js";

// ------------------------------------------------------------------
// Boot
// ------------------------------------------------------------------
var renderers = {
  settings: renderSettings,
  onboarding: renderOnboarding,
  voices: renderVoiceManager,
  notices: renderNotices,
  overlay: renderOverlay,
};

// Wire footer buttons ONCE per document on the settings surface.
// wireFooter() uses addEventListener with NO removal; calling it more
// than once would double-bind Save/Apply (double-save bug). It is
// intentionally NOT called inside renderers.settings so __pippalRefresh
// can re-run renderSettings() to refresh data without re-wiring.
if (SURFACE === "settings" || !SURFACE) {
  wireFooter();
}

// i18n readiness gate: surface renderers call window.t() for their
// dynamic strings (T-104 extraction), so they must not run until the
// catalogs are loaded. i18n.js sets <html data-i18n-ready> AFTER it has
// the catalog + DOM (desktop host injects synchronously; the served
// harness fetches under the anti-FOUC cloak). Waiting for that attribute
// guarantees t() resolves real strings instead of the ⟦key⟧ marker,
// while keeping English output byte-identical (the gate only defers, it
// never changes any text). A watchdog resolves anyway so a stalled
// catalog fetch can never leave the surface permanently unrendered.
function whenI18nReady() {
  // Preferred: the actual catalog-load promise i18n.js exposes. It resolves
  // exactly when the catalogs are loaded (or a fetch has definitively failed
  // to {}), never prematurely — unlike the data-i18n-ready attribute, which
  // the 3000 ms reveal watchdog can set before a slow fetch resolves.
  var ready = window.__PIPPAL_I18N_READY__;
  if (ready && typeof ready.then === "function") {
    return Promise.resolve(ready).catch(function () {});
  }
  // Fallback (older engine without the promise): observe the ready attribute.
  return new Promise(function (resolve) {
    var html = document.documentElement;
    if (html.hasAttribute("data-i18n-ready")) {
      resolve();
      return;
    }
    var done = false;
    function finish() {
      if (done) return;
      done = true;
      if (obs) obs.disconnect();
      resolve();
    }
    var obs = null;
    if (typeof MutationObserver === "function") {
      obs = new MutationObserver(function () {
        if (html.hasAttribute("data-i18n-ready")) finish();
      });
      obs.observe(html, {
        attributes: true,
        attributeFilter: ["data-i18n-ready"],
      });
    }
    // Belt-and-braces: reveal watchdog in i18n.js fires at 3000 ms, so a
    // slightly longer fallback here guarantees the surface always renders.
    setTimeout(finish, 3500);
  });
}

function renderSurface() {
  return whenI18nReady()
    .then(function () {
      return (renderers[SURFACE] || renderers.settings)();
    })
    .then(function () {
      document.body.setAttribute("data-ready", SURFACE);
    })
    .catch(fail);
}

// __pippalRefresh: in-place data refresh hook called by Python on
// hide()->show() reopen (window_lifecycle.open via evaluate_js).
// Re-runs ONLY the data renderer (NOT wireFooter) to refresh DOM
// from get_config() / get_queue() / etc. and re-asserts data-ready.
// Guard (&&) makes it a no-op on surfaces that don't register it.
window.__pippalRefresh = renderSurface;

renderSurface();
