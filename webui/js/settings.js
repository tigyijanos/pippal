/* settings.js — Settings surface entry. Free build: Piper voices only. */
"use strict";

import {
  U,
  API,
  t,
  view,
  footer,
  toast,
  fail,
  settingsState,
  INSTALLED_VOICES_CHANGED_EVENT,
  INSTALLED_VOICES_CHANGED_KEY,
} from "./app-core.js";
import { buildLanguageCard, buildDiagCard } from "./settings-cards.js";
import { ctxText } from "./settings-footer.js";
import { buildPiperSpeakerRow } from "./piper-speakers.js";
// ------------------------------------------------------------------
// Promotional URLs — kept as named constants for clarity and testability.
// ------------------------------------------------------------------
var STORE_URL = "https://apps.microsoft.com/detail/9p0jx4n42nsl";
// The Reddit community URL is intentionally NOT rendered in the promo banner —
// it already appears in the About card (about_info links, key "reddit").
// Keeping it as a constant for reference / test tooling only.
var REDDIT_URL = "https://www.reddit.com/r/PipPalApp/";

// ------------------------------------------------------------------
// Speed <-> length_scale converters (shared with settings-footer.js).
// ------------------------------------------------------------------
var teardownSettingsVoiceRefresh = null;

export function speedToLengthScale(speed) {
  return Math.round((1.0 / speed) * 1000) / 1000;
}
export function lengthScaleToSpeed(ls) {
  return ls ? Math.round((1.0 / ls) * 100) / 100 : 1.0;
}

export function renderSettings() {
  if (teardownSettingsVoiceRefresh) {
    teardownSettingsVoiceRefresh();
    teardownSettingsVoiceRefresh = null;
  }
  return Promise.all([
    API.call("get_config"),
    API.call("get_defaults"),
    API.call("get_engines"),
    API.call("get_installed_voices"),
    API.call("get_hotkey_actions"),
    API.call("context_menu_status"),
    API.call("about_info"),
    API.call("get_diag_state"),
  ]).then(function (res) {
    var cfg = res[0],
      defs = res[1],
      engines = res[2],
      voices = res[3];
    var hotkeys = res[4],
      ctxStatus = res[5],
      about = res[6];
    var diagState = res[7] || {
      level: "off",
      levels: ["off", "error", "trace"],
      log_count: 0,
      total_bytes: 0,
      folder: "",
      anon_id: "",
      notice: "",
    };

    settingsState.config = cfg;
    settingsState.defaults = defs;
    settingsState.controls = {};

    document.getElementById("brand-name").textContent =
      cfg.brand_name || "PipPal";

    view.innerHTML = "";
    footer.classList.remove("hidden");

    // ---- Voice card (Engine + Voice + Manage -- no Kokoro extras) ----
    var engineSel = U.select(
      "settings-engine",
      engines.map(function (e) {
        return { value: e, label: e };
      }),
      cfg.engine || "piper",
    );
    engineSel.classList.add("grow");

    var piperVoiceOpts = voices.length
      ? voices.map(function (v) {
          return { value: v, label: v };
        })
      : [{ value: "", label: t("settings.voice.none") }];
    var voiceSel = U.select(
      "settings-voice",
      piperVoiceOpts,
      voices.indexOf(cfg.voice) >= 0 ? cfg.voice : voices[0] || "",
    );
    voiceSel.classList.add("grow");
    if (!voices.length) voiceSel.disabled = true;
    settingsState.controls.engine = engineSel;
    settingsState.controls.voice = voiceSel;
    var manageBtn = U.el("button", {
      testid: "settings-manage-voices",
      text: voices.length
        ? t("settings.voice.manage")
        : t("settings.voice.install_voices"),
    });
    manageBtn.addEventListener("click", function () {
      API.call("open_voice_manager_window").catch(fail);
    });
    var engineHint = U.el("div", {
      class: "card-hint",
      testid: "settings-engine-hint",
      text: voices.length
        ? t("settings.voice.hint_installed")
        : t("settings.voice.hint_empty"),
    });
    var voiceCard = U.card(t("settings.voice.title"), [
      U.fieldRow(t("settings.voice.engine_label"), engineSel),
      U.el("div", { class: "row", testid: "settings-voice-row" }, [
        U.el("label", {
          class: "field-label",
          text: t("settings.voice.voice_label"),
        }),
        voiceSel,
        manageBtn,
      ]),
      buildPiperSpeakerRow(voiceSel, engineSel, cfg),
      engineHint,
    ]);

    // Live-refresh the voice list when voices are installed in the Voices
    // window.
    var piperVoiceRefreshToken = 0;
    function refreshPiperVoices() {
      var token = ++piperVoiceRefreshToken;
      return API.call("get_installed_voices")
        .then(function (freshVoices) {
          if (token !== piperVoiceRefreshToken) return;
          voices = Array.isArray(freshVoices) ? freshVoices : [];
          manageBtn.textContent = voices.length
            ? t("settings.voice.manage")
            : t("settings.voice.install_voices");
          var newOpts = voices.length
            ? voices.map(function (v) {
                return { value: v, label: v };
              })
            : [{ value: "", label: t("settings.voice.none") }];
          var currentVal = voiceSel.value;
          while (voiceSel.firstChild) voiceSel.removeChild(voiceSel.firstChild);
          newOpts.forEach(function (opt) {
            var o = document.createElement("option");
            o.value = opt.value;
            o.textContent = opt.label;
            if (opt.value === currentVal) o.selected = true;
            voiceSel.appendChild(o);
          });
          voiceSel.disabled = !voices.length;
          engineHint.textContent = voices.length
            ? t("settings.voice.hint_installed")
            : t("settings.voice.hint_empty"); voiceSel.dispatchEvent(new CustomEvent("change"));
        })
        .catch(fail);
    }
    function onInstalledVoicesChanged() {
      refreshPiperVoices();
    }
    function onInstalledVoicesStorage(e) {
      if (e.key === INSTALLED_VOICES_CHANGED_KEY) refreshPiperVoices();
    }
    window.addEventListener(
      INSTALLED_VOICES_CHANGED_EVENT,
      onInstalledVoicesChanged,
    );
    window.addEventListener("storage", onInstalledVoicesStorage);
    teardownSettingsVoiceRefresh = function () {
      window.removeEventListener(
        INSTALLED_VOICES_CHANGED_EVENT,
        onInstalledVoicesChanged,
      );
      window.removeEventListener("storage", onInstalledVoicesStorage);
    };

    // ---- Speech card ----
    var speed = U.sliderRow(
      t("settings.speech.speed_label"),
      "settings-speed",
      0.6,
      1.7,
      0.01,
      lengthScaleToSpeed(parseFloat(cfg.length_scale || 1.0)),
      function (v) {
        return v.toFixed(2) + "\xd7";
      },
    );
    var noise = U.sliderRow(
      t("settings.speech.variation_label"),
      "settings-noise",
      0.3,
      1.0,
      0.01,
      parseFloat(cfg.noise_scale != null ? cfg.noise_scale : 0.667),
      function (v) {
        return v.toFixed(2);
      },
    );
    settingsState.controls.speed = speed.slider;
    settingsState.controls.noise_scale = noise.slider;
    var speechCard = U.card(t("settings.speech.title"), [
      speed.node,
      noise.node,
      U.hint(t("settings.speech.hint")),
    ]);

    // ---- Hotkeys card ----
    var hkRows = [];
    hotkeys.forEach(function (a) {
      var key = a[1],
        // The registered label (a[2]) is an i18n catalog KEY for built-in
        // actions. t() renders it; when neither the active nor the fallback
        // catalog has the key it returns the "⟦key⟧" marker, which
        // means a third-party plugin registered a plain-English label — fall
        // back to that raw string so the plugin API stays compatible.
        label = (function (raw) {
          var s = t(raw);
          return s === "⟦" + raw + "⟧" ? raw : s;
        })(a[2]),
        def = a[3];
      var inp = U.el("input", { type: "text", testid: "settings-" + key });
      inp.classList.add("grow");
      inp.value = cfg[key] != null ? cfg[key] : def;
      settingsState.controls[key] = inp;
      hkRows.push(U.fieldRow(label, inp));
    });
    hkRows.push(U.hint(t("settings.hotkeys.hint")));
    var hotkeysCard = U.card(t("settings.hotkeys.title"), hkRows);

    // ---- Reader panel card ----
    var showPanel = U.checkRow(
      "settings-show_overlay",
      t("settings.panel.show_overlay"),
      cfg.show_overlay,
    );
    var showText = U.checkRow(
      "settings-show_text_in_overlay",
      t("settings.panel.show_text"),
      cfg.show_text_in_overlay,
    );
    settingsState.controls.show_overlay = showPanel.querySelector("input");
    settingsState.controls.show_text_in_overlay =
      showText.querySelector("input");
    var autoHide = U.spinRow(
      t("settings.panel.auto_hide_label"),
      "settings-auto_hide_ms",
      300,
      8000,
      100,
      cfg.auto_hide_ms != null ? cfg.auto_hide_ms : 1500,
      t("settings.panel.auto_hide_unit"),
    );
    var distance = U.spinRow(
      t("settings.panel.distance_label"),
      "settings-overlay_y_offset",
      20,
      600,
      10,
      cfg.overlay_y_offset != null ? cfg.overlay_y_offset : 100,
      t("settings.panel.distance_unit"),
    );
    var karaoke = U.spinRow(
      t("settings.panel.karaoke_label"),
      "settings-karaoke_offset_ms",
      -300,
      600,
      20,
      cfg.karaoke_offset_ms != null ? cfg.karaoke_offset_ms : 120,
      t("settings.panel.karaoke_unit"),
    );
    settingsState.controls.auto_hide_ms = autoHide.input;
    settingsState.controls.overlay_y_offset = distance.input;
    settingsState.controls.karaoke_offset_ms = karaoke.input;
    var panelCard = U.card(t("settings.panel.title"), [
      showPanel,
      showText,
      autoHide.node,
      distance.node,
      karaoke.node,
    ]);

    // ---- Windows integration card ----
    var ctxStatusEl = U.el("div", {
      class: "card-label",
      testid: "settings-ctx-status",
      text: ctxText(ctxStatus),
    });
    var installBtn = U.el("button", {
      testid: "settings-ctx-install",
      text: t("settings.integration.install"),
    });
    var removeBtn = U.el("button", {
      class: "danger",
      testid: "settings-ctx-remove",
      text: t("settings.integration.remove"),
    });
    installBtn.addEventListener("click", function () {
      API.call("install_context_menu")
        .then(function (st) {
          ctxStatusEl.textContent = ctxText(st);
          toast(t("settings.integration.installed_toast"));
        })
        .catch(fail);
    });
    removeBtn.addEventListener("click", function () {
      API.call("remove_context_menu")
        .then(function (st) {
          ctxStatusEl.textContent = ctxText(st);
        })
        .catch(fail);
    });
    var intCard = U.card(t("settings.integration.title"), [
      ctxStatusEl,
      U.hint(t("settings.integration.hint")),
      U.el("div", { class: "row", style: "margin-top:8px" }, [
        installBtn,
        removeBtn,
      ]),
    ]);

    // ---- Language card ----
    var languageCard = buildLanguageCard(cfg);

    // ---- Diagnostics card ----
    var diagCard = buildDiagCard(diagState);

    // ---- Open-source notices card ----
    var noticesBtn = U.el("button", {
      testid: "settings-view-licences",
      text: t("settings.notices.view"),
    });
    noticesBtn.addEventListener("click", function () {
      API.call("open_notices_window").catch(fail);
    });
    var noticesCard = U.card(t("settings.notices.title"), [
      U.hint(t("settings.notices.hint")),
      U.el("div", { class: "row", style: "margin-top:8px" }, [noticesBtn]),
    ]);

    // ---- About card ----
    var linkRow = U.el(
      "div",
      { class: "link-row" },
      about.links.map(function (l) {
        var a = U.el("span", {
          class: "link",
          text: l.text,
          testid: "about-" + l.key,
        });
        a.addEventListener("click", function () {
          API.call("open_url", l.url).catch(fail);
        });
        return a;
      }),
    );
    var aboutCard = U.card(t("settings.about.title"), [
      U.el("div", {
        class: "card-label",
        style: "font-family:var(--font-semibold)",
        text: (cfg.brand_name || "PipPal") + " " + about.version,
        "data-testid": "about-version-label",
      }),
      U.el("div", {
        class: "card-hint",
        text: t("settings.about.tagline"),
      }),
      U.el("div", {
        class: "card-hint",
        style: "margin-top:8px",
        text: t("settings.about.copyright"),
      }),
      linkRow,
    ]);

    // ---- Promo banner (free → Pro upsell) ----
    // NOTE: Reddit community link is NOT included here — it already appears in
    //       the About card (about_info links, key "reddit"). Adding it here
    //       caused it to be shown twice to the user.
    var promoGetProBtn = U.el("button", {
      testid: "promo-get-pro",
      text: t("promo.get_pro"),
    });
    promoGetProBtn.classList.add("primary");
    promoGetProBtn.addEventListener("click", function () {
      API.call("open_url", STORE_URL).catch(fail);
    });

    var promoCard = U.el(
      "div",
      { testid: "settings-promo", class: "settings-promo" },
      [
        U.el("div", { class: "promo-pro-cta" }, [
          U.el("div", {
            class: "promo-pro-headline",
            text: t("promo.headline"),
          }),
          U.el("div", {
            class: "promo-pro-sub",
            text: t("promo.sub"),
          }),
          promoGetProBtn,
        ]),
      ],
    );

    view.appendChild(promoCard);
    view.appendChild(voiceCard);
    view.appendChild(languageCard);
    view.appendChild(speechCard);
    view.appendChild(hotkeysCard);
    view.appendChild(panelCard);
    view.appendChild(intCard);
    view.appendChild(diagCard);
    view.appendChild(noticesCard);
    view.appendChild(aboutCard);
  });
}
