/* i18n.js — PipPal web-UI internationalization runtime + anti-FOUC boot.
 *
 * A BLOCKING, CLASSIC script loaded in <head> BEFORE the module graph
 * (main.js is type="module" and therefore deferred, so this runs first
 * and window.t exists before any surface renderer evaluates).
 *
 * Responsibilities (T-101, engine only — no UI strings are extracted
 * here; that is T-104):
 *
 *   1. Resolve the active language synchronously:
 *        window.__PIPPAL_LANG__ (host-injected, already validated)
 *          -> ?lang= query param
 *          -> navigator.language / navigator.languages[0]
 *          -> "en"
 *   2. Expose window.t(key, params) with the fallback chain
 *        active-lang catalog -> en catalog -> "⟦key⟧" marker.
 *   3. CLDR plurals via Intl.PluralRules (probed at boot; if the
 *      platform lacks it we fall back to the "other" category).
 *   4. "{name}" named-placeholder interpolation (missing param leaves
 *      the literal "{name}" — the completeness linter forbids that in
 *      shipped catalogs/tests).
 *   5. Anti-FOUC cloak: <html class="i18n-cloak"> is visibility:hidden
 *      until this script has (a) the catalog and (b) the DOM, then it
 *      fills the static-chrome data-i18n attributes, sets
 *      document.documentElement.lang, removes the cloak class and marks
 *      <html data-i18n-ready>. English output stays byte-identical
 *      (the cloak only toggles a class; it never changes text).
 *
 * Two catalog-delivery paths converge on the same window.t:
 *   (a) Desktop host: Python injects window.__PIPPAL_LANG__ and
 *       window.__PIPPAL_CAT__ (and optionally window.__PIPPAL_CAT_EN__)
 *       synchronously at window creation — no fetch, no flash.
 *   (b) Served harness (no Python host): ?lang=<tag> selects the
 *       language and this script fetches i18n/<tag>.json (plus the en
 *       fallback) under the cloak before revealing.
 */
(function () {
  "use strict";

  // U+27E6 / U+27E7 mathematical white square brackets — a greppable
  // "missing translation" marker the completeness linter + per-language
  // smoke assert never appears in a shipped surface.
  var MARK_OPEN = "⟦";
  var MARK_CLOSE = "⟧";
  var FALLBACK_LANG = "en";

  // The languages this build ships (or will ship) catalogs for. This is
  // the single JS-side supported list; navigator.language and ?lang= are
  // mapped onto it. Adding language #7 = drop its <lang>.json + add the
  // tag here (kept deliberately data-shaped for that reason). Note the
  // engine still works with any catalog it is *handed* via the host
  // globals — this list only governs system/query resolution.
  var SUPPORTED = ["en", "zh-CN", "de", "hu", "uk", "pt-BR"];

  // --- language resolution -------------------------------------------

  /** Map an arbitrary BCP-47 tag onto a SUPPORTED tag, or null. */
  function mapToSupported(tag) {
    if (!tag) return null;
    var raw = String(tag).trim();
    if (!raw) return null;
    var lower = raw.toLowerCase();
    // Exact (case-insensitive) match first.
    for (var i = 0; i < SUPPORTED.length; i++) {
      if (SUPPORTED[i].toLowerCase() === lower) return SUPPORTED[i];
    }
    var primary = lower.split("-")[0];
    // Macro-language / regional normalisation onto the chosen variants.
    if (primary === "zh") return "zh-CN";
    if (primary === "pt") return "pt-BR";
    // Bare primary subtag match (e.g. "de-DE" -> "de", "uk-UA" -> "uk").
    for (var j = 0; j < SUPPORTED.length; j++) {
      if (SUPPORTED[j].toLowerCase() === primary) return SUPPORTED[j];
    }
    return null;
  }

  function queryLang() {
    try {
      return new URLSearchParams(window.location.search).get("lang");
    } catch (e) {
      return null;
    }
  }

  function navigatorLang() {
    var nav = window.navigator || {};
    if (nav.languages && nav.languages.length) return nav.languages[0];
    return nav.language || null;
  }

  function resolveLang() {
    // 1. Host-injected (Python/harness has already resolved+validated).
    if (window.__PIPPAL_LANG__) return String(window.__PIPPAL_LANG__);
    // 2. Explicit ?lang= override (the served test harness). Honoured
    //    when it maps onto a supported language; unsupported values fall
    //    through rather than pinning an unknown tag.
    var mappedQuery = mapToSupported(queryLang());
    if (mappedQuery) return mappedQuery;
    // 3. System language, mapped onto the supported set.
    var mappedNav = mapToSupported(navigatorLang());
    if (mappedNav) return mappedNav;
    // 4. Fallback.
    return FALLBACK_LANG;
  }

  var LANG = resolveLang();

  // --- plural probe ---------------------------------------------------

  var HAS_PLURAL_RULES =
    typeof Intl !== "undefined" && typeof Intl.PluralRules === "function";

  // Cache one selector PER language: a plural key resolves against the
  // language of the catalog it was found in (active vs en fallback), so
  // pluralCategory can be called with more than one lang per boot.
  var _pluralSelectors = {};
  function pluralCategory(lang, n) {
    if (!HAS_PLURAL_RULES) return "other";
    try {
      var sel = _pluralSelectors[lang];
      if (!sel) {
        sel = new Intl.PluralRules(lang);
        _pluralSelectors[lang] = sel;
      }
      return sel.select(Number(n));
    } catch (e) {
      // An unknown/rejected locale -> a permissive default rather than a
      // hard failure (the engine must never throw from t()).
      return "other";
    }
  }

  /** The language a catalog is written in (its _meta.lang), used to pick
   *  the plural category. Falls back to the resolved active LANG. */
  function catalogLang(catalog) {
    if (catalog && catalog._meta && catalog._meta.lang) {
      return catalog._meta.lang;
    }
    return LANG;
  }

  // --- catalog state + t() -------------------------------------------

  // active = the resolved language's catalog; fallback = en. Both start
  // empty and are populated (sync from host globals or async via fetch)
  // before the cloak is lifted. t() is defined immediately so it exists
  // before the module graph; until the catalogs load it simply falls
  // back to the marker (existing surfaces do not call t() yet in T-101).
  var _active = {};
  var _fallback = {};

  function interpolate(template, params) {
    if (!params) return template;
    // Mirror the Python engine's placeholder shape exactly: \{(\w+)\}.
    // A word-only name (no spaces/dots/hyphens) keeps "{ name }",
    // "{user.name}" and "{file-id}" LITERAL in BOTH runtimes.
    return template.replace(/\{(\w+)\}/g, function (whole, name) {
      if (Object.prototype.hasOwnProperty.call(params, name)) {
        return String(params[name]);
      }
      return whole; // missing param -> leave the literal "{name}"
    });
  }

  /** Resolve a raw catalog value (scalar or plural object) to a string
   *  template for the given params, or null if the value is absent. */
  function resolveValue(catalog, key, params) {
    if (!catalog || !Object.prototype.hasOwnProperty.call(catalog, key)) {
      return null;
    }
    var value = catalog[key];
    if (value === null || value === undefined) return null;
    if (typeof value === "string") return value;
    if (typeof value === "object") {
      // Plural object: { "_plural": "count", "one": "...", "other": "..." }
      var countName = value._plural;
      var n = params && countName ? params[countName] : undefined;
      // Missing count defaults to 0 (mirrors the Python engine) so a
      // plural key rendered without a count is deterministic across both
      // runtimes (e.g. pt-BR: no count -> 0 -> "one").
      if (n === undefined || n === null) n = 0;
      // Select the category using the language of the catalog the key was
      // FOUND in (the design contract), not necessarily the active LANG.
      var category = pluralCategory(catalogLang(catalog), n);
      if (Object.prototype.hasOwnProperty.call(value, category)) {
        return value[category];
      }
      if (Object.prototype.hasOwnProperty.call(value, "other")) {
        return value.other;
      }
      return null;
    }
    return null;
  }

  function t(key, params) {
    if (key === null || key === undefined) return "";
    var template = resolveValue(_active, key, params);
    if (template === null) template = resolveValue(_fallback, key, params);
    if (template === null) return MARK_OPEN + key + MARK_CLOSE;
    return interpolate(template, params);
  }

  // Diagnostic seam for tests / debugging (oracle-first: assert lang +
  // plural-probe state directly, not implementation internals).
  t.diag = function () {
    return {
      lang: LANG,
      hasPluralRules: HAS_PLURAL_RULES,
      ready: !!document.documentElement.hasAttribute("data-i18n-ready"),
    };
  };
  t.lang = LANG;
  t.supported = SUPPORTED.slice();

  window.t = t;
  window.__PIPPAL_I18N__ = t; // stable alias for host/pro reuse

  // --- static-chrome fills + reveal ----------------------------------

  function applyStaticChrome(root) {
    var scope = root || document;
    // textContent fills.
    var textNodes = scope.querySelectorAll("[data-i18n]");
    for (var i = 0; i < textNodes.length; i++) {
      var el = textNodes[i];
      var key = el.getAttribute("data-i18n");
      if (key) el.textContent = t(key);
    }
    // Attribute fills: data-i18n-<attr> -> element[attr] (title,
    // aria-label, placeholder, ...). Keeps the close button's glyph as
    // textContent while translating its title/aria-label.
    var attrNodes = scope.querySelectorAll("*");
    for (var j = 0; j < attrNodes.length; j++) {
      var node = attrNodes[j];
      if (!node.attributes) continue;
      for (var k = 0; k < node.attributes.length; k++) {
        var attr = node.attributes[k];
        if (attr.name.indexOf("data-i18n-") === 0) {
          var target = attr.name.slice("data-i18n-".length);
          var tKey = attr.value;
          if (target && tKey) node.setAttribute(target, t(tKey));
        }
      }
    }
  }

  var _revealed = false;
  function reveal() {
    if (_revealed) return;
    _revealed = true;
    var html = document.documentElement;
    try {
      html.setAttribute("lang", LANG);
      applyStaticChrome(document);
    } catch (e) {
      // Never let a fill error keep the UI cloaked — English chrome is
      // already in the HTML, so revealing as-is is still correct.
      if (window.console && console.warn) {
        console.warn("i18n: static-chrome fill failed", e);
      }
    } finally {
      html.classList.remove("i18n-cloak");
      html.setAttribute("data-i18n-ready", "");
    }
  }

  // --- catalog loading ------------------------------------------------

  function fetchCatalog(tag) {
    return fetch("i18n/" + tag + ".json", { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) return {};
        return r.json();
      })
      .catch(function () {
        return {};
      });
  }

  function loadCatalogs() {
    // en fallback: host-injected, or the active catalog when LANG is en,
    // otherwise fetched.
    var enPromise;
    if (window.__PIPPAL_CAT_EN__) {
      enPromise = Promise.resolve(window.__PIPPAL_CAT_EN__);
    } else if (LANG === FALLBACK_LANG && window.__PIPPAL_CAT__) {
      enPromise = Promise.resolve(window.__PIPPAL_CAT__);
    } else {
      enPromise = fetchCatalog(FALLBACK_LANG);
    }

    // active catalog: host-injected, or the en fallback when LANG is en,
    // otherwise fetched (a 404 yields {} so t() falls back to en).
    var activePromise;
    if (window.__PIPPAL_CAT__) {
      activePromise = Promise.resolve(window.__PIPPAL_CAT__);
    } else if (LANG === FALLBACK_LANG) {
      activePromise = enPromise;
    } else {
      activePromise = fetchCatalog(LANG);
    }

    return Promise.all([activePromise, enPromise]).then(function (cats) {
      _active = cats[0] || {};
      _fallback = cats[1] || {};
    });
  }

  function domReady() {
    return new Promise(function (resolve) {
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
          resolve();
        });
      } else {
        resolve();
      }
    });
  }

  // Load catalogs and DOM in parallel, then reveal. A watchdog reveals
  // anyway if catalog loading stalls, so a fetch hiccup can never leave
  // the UI permanently cloaked (zero-regression guarantee).
  var _catalogsReady = loadCatalogs();
  Promise.all([_catalogsReady, domReady()]).then(reveal, reveal);
  setTimeout(reveal, 3000);
})();
