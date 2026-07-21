/* Searchable, bounded picker for installed Piper multi-speaker models. */
"use strict";

import { U, API, t, settingsState, fail } from "./app-core.js";

var RESULT_LIMIT = 50;

export function buildPiperSpeakerRow(voiceSel, engineSel, cfg) {
  var saved = Object.assign({}, cfg.piper_speaker_ids || {});
  settingsState.controls.piper_speaker_ids = { value: saved };
  var search = U.el("input", { type: "search", testid: "settings-piper-speaker-search" });
  search.classList.add("grow");
  var picker = U.select("settings-piper-speaker", [], "");
  picker.classList.add("grow");
  var hint = U.el("div", { class: "card-hint" });
  var requestSequence = 0;
  var row = U.el("div", { testid: "settings-piper-speaker-row" }, [
    U.fieldRow(t("settings.voice.speaker_search"), search),
    U.fieldRow(t("settings.voice.speaker_label"), picker),
    hint,
  ]);
  row.style.display = "none";

  function replaceOptions(state, query) {
    var speakers = state.speakers || [];
    while (picker.firstChild) picker.removeChild(picker.firstChild);
    speakers.forEach(function (speaker) {
      var option = document.createElement("option");
      option.value = String(speaker.id);
      option.textContent = speaker.label;
      picker.appendChild(option);
    });
    var optionIds = new Set(speakers.map(function (speaker) {
      return String(speaker.id);
    }));
    var selected = saved[voiceSel.value];
    if (selected == null || !optionIds.has(String(selected))) {
      selected = state.selected;
    }
    if (selected == null || !optionIds.has(String(selected))) selected = null;
    if (selected == null && !query && speakers.length) selected = speakers[0].id;
    if (selected != null) {
      picker.value = String(selected);
      if (!query) saved[voiceSel.value] = parseInt(String(selected), 10);
    } else picker.value = "";
    picker.disabled = !speakers.length;
    hint.textContent = t("settings.voice.speaker_hint", {
      total: state.total,
      limit: RESULT_LIMIT,
    });
  }

  function refresh() {
    var sequence = ++requestSequence;
    var requestedVoice = voiceSel.value;
    var requestedQuery = search.value.trim();
    if (engineSel.value !== "piper" || !requestedVoice) {
      row.style.display = "none";
      return Promise.resolve();
    }
    var requestedSelection = saved[requestedVoice];
    return API.call(
      "get_piper_speakers",
      requestedVoice,
      requestedQuery,
      requestedSelection == null ? null : requestedSelection,
    )
      .then(function (state) {
        if (
          sequence !== requestSequence ||
          voiceSel.value !== requestedVoice ||
          engineSel.value !== "piper"
        ) return;
        if (!state || state.total <= 1) {
          row.style.display = "none";
          return;
        }
        row.style.display = "";
        replaceOptions(state, requestedQuery);
      })
      .catch(function (error) {
        if (sequence !== requestSequence) return;
        row.style.display = "none";
        fail(error);
      });
  }

  picker.addEventListener("change", function () {
    if (voiceSel.value && picker.value) {
      saved[voiceSel.value] = parseInt(picker.value, 10);
    }
  });
  voiceSel.addEventListener("change", function () {
    search.value = "";
    refresh();
  });
  engineSel.addEventListener("change", function () { setTimeout(refresh, 0); });
  var debounce;
  search.addEventListener("input", function () {
    clearTimeout(debounce);
    debounce = setTimeout(refresh, 180);
  });
  refresh();
  return row;
}
