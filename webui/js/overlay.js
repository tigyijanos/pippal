/* overlay.js — the reader OVERLAY karaoke panel (overlay.py /
 * overlay_paint.py) plus the shared closeWin() helper.
 * Refactored from app.js/main.js (renderOverlay, closeWin);
 * behavior-preserving — same DOM, same data-testid values, same
 * setInterval(tick, 120) cadence, same .reader-loading "thinking"
 * block. Isolated as its own module so the event-driven loading-state
 * follow-up touches only this file. Shared singletons come from app-core.js. */
"use strict";

import {
  U,
  API,
  t,
  view,
  footer,
  fail,
  handleCloseWindowFailure,
} from "./app-core.js";

// ------------------------------------------------------------------
// Playful loading messages — whimsical, fake-technical lines in
// the charming STYLE of classic life-sim loading screens, tailored to
// a text-to-speech READER. ORIGINAL strings (no trademarked phrases).
// They rotate while the overlay is in the loading/thinking state; see
// the rotation logic in tick() below.
//
// T-104: the lines are now catalog KEYS, resolved through t() at
// display time (English values live in webui/i18n/en.json under
// overlay.loading.*; other languages + width budget land in T-106).
// ------------------------------------------------------------------
var LOADING_MESSAGES = [
  "overlay.loading.warmup",
  "overlay.loading.reticulating",
  "overlay.loading.breathe",
  "overlay.loading.summoning",
  "overlay.loading.untangling",
  "overlay.loading.polishing",
  "overlay.loading.brewing",
  "overlay.loading.tuning",
  "overlay.loading.vowels",
  "overlay.loading.pauses",
  "overlay.loading.buffering",
  "overlay.loading.smoothing",
  "overlay.loading.calibrating",
  "overlay.loading.intonation",
];
// Each rotating message is shown for this long before advancing.
var LOADING_ROTATE_MS = 1800;
// Random starting offset so different reads don't always begin the same.
var loadingMsgBase = Math.floor(Math.random() * LOADING_MESSAGES.length);
function currentLoadingMessage() {
  var step = Math.floor(Date.now() / LOADING_ROTATE_MS);
  var idx = (loadingMsgBase + step) % LOADING_MESSAGES.length;
  return t(LOADING_MESSAGES[idx]);
}

function escapeLoadingText(s) {
  return String(s).replace(/[<>&"]/g, function (c) {
    return { "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c];
  });
}

// ------------------------------------------------------------------
// READER OVERLAY panel (overlay.py / overlay_paint.py — the
// karaoke port is the shared core WebOverlay + this paint code,
// identical to the public frontend so visuals can't drift).
//
// Window architecture: the overlay is a NORMAL opaque frameless window
// (same pattern as Settings).  Drag uses the .pywebview-drag-region
// mechanism — the brand area (icon + dot + label) is wrapped in a
// .overlay-drag-region span that carries .pywebview-drag-region, so the
// user can drag the window by the header brand area.  The transport
// buttons and close button are siblings of the drag region (NOT
// descendants) so clicking them never triggers a window drag.
// ------------------------------------------------------------------
export function renderOverlay() {
  document.body.classList.add("overlay-mode");
  document.getElementById("titlebar").classList.add("hidden");
  footer.classList.add("hidden");
  view.style.padding = "0";
  view.innerHTML = "";

  var dot = U.el("span", { class: "overlay-dot", testid: "overlay-dot" });
  var label = U.el("span", {
    class: "ohlabel",
    testid: "overlay-label",
    text: "PipPal",
  });
  // Brand area: icon + dot + label wrapped in a drag region.
  // .pywebview-drag-region makes pywebview's WebView2 backend honour the
  // drag even with easy_drag=False — same as Settings titlebar in index.html.
  var dragRegion = U.el(
    "span",
    {
      class: "overlay-drag-region pywebview-drag-region",
      testid: "overlay-drag-region",
    },
    [U.el("img", { src: "assets/pippal_icon.png" }), dot, label],
  );
  var closeBtn = U.el("button", {
    class: "overlay-close",
    testid: "overlay-close",
  });
  var bodyEl = U.el("div", { class: "overlay-body", testid: "overlay-text" });
  // Loading indicator: shown while synthesis is in progress
  // (overlay_state == "thinking"), hidden during reading/idle/done.
  var loadingEl = U.el("div", {
    class: "overlay-loading hidden",
    testid: "overlay-loading",
  });
  var barFill = U.el("div");
  var counter = U.el("span", {
    class: "overlay-counter",
    testid: "overlay-page-marker",
    text: "",
  });
  var legacyCounterMarker = U.el("span", {
    testid: "overlay-counter",
    "aria-hidden": "true",
    style: "display:none",
    text: "",
  });
  // SVG icon helpers — all icons share the same 16×16 viewBox so every
  // glyph occupies an identical box.  This eliminates the per-glyph
  // vertical-metric differences that unicode transport characters have
  // across font families (fixes icon-top misalignment).
  function svgIcon(pathD, extraAttrs) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", "14");
    svg.setAttribute("height", "14");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("fill", "currentColor");
    if (extraAttrs) {
      Object.keys(extraAttrs).forEach(function (k) {
        svg.setAttribute(k, extraAttrs[k]);
      });
    }
    var path = document.createElementNS(ns, "path");
    path.setAttribute("d", pathD);
    svg.appendChild(path);
    return svg;
  }
  // Icon path data (16×16 viewBox, pixel-hinted, same visual weight):
  // prev  (⏮): bar on left + filled triangle pointing left
  // replay(↺): circular arrow CCW
  // pause (⏸): two vertical bars
  // next  (⏭): filled triangle pointing right + bar on right
  // close (✕): thin X
  var ICONS = {
    prev: "M2 3h1.5v10H2V3zm10.5 1.06L6.06 8l6.44 3.94V4.06z",
    replay:
      "M8 2.5a5.5 5.5 0 1 0 5.5 5.5h-1.5A4 4 0 1 1 8 4v1.5l3-2.25L8 1V2.5z",
    pause: "M4 3h2.5v10H4V3zm5.5 0H12v10H9.5V3z",
    play: "M4 3.06v9.88L13 8 4 3.06z",
    next: "M12.5 3H14v10h-1.5V3zM3.5 4.06v7.88L9.94 8 3.5 4.06z",
    close:
      "M3.22 3.22a.75.75 0 0 1 1.06 0L8 6.94l3.72-3.72a.75.75 0 1 1 1.06 1.06L9.06 8l3.72 3.72a.75.75 0 1 1-1.06 1.06L8 9.06l-3.72 3.72a.75.75 0 0 1-1.06-1.06L6.94 8 3.22 4.28a.75.75 0 0 1 0-1.06z",
  };
  // Populate the close button (created before ICONS was defined above).
  closeBtn.appendChild(svgIcon(ICONS.close));
  function obtn(tag) {
    var b = U.el("button", {
      class: "obtn",
      testid: "overlay-" + tag,
    });
    b.appendChild(svgIcon(ICONS[tag]));
    b.addEventListener("click", function () {
      API.call("overlay_action", tag).catch(fail);
    });
    return b;
  }
  // Transport buttons: siblings of dragRegion (not inside it) so clicks
  // are never hijacked by the drag region.
  var prevBtn = obtn("prev");
  var replayBtn = obtn("replay");
  var pauseBtn = obtn("pause");
  var nextBtn = obtn("next");
  // Header: [dragRegion(brand)] [transport buttons] [close]
  var head = U.el("div", { class: "overlay-head" }, [
    dragRegion,
    prevBtn,
    replayBtn,
    pauseBtn,
    nextBtn,
    closeBtn,
  ]);
  // Footer: progress bar + counter.
  var progress = U.el("div", { class: "overlay-progress" }, [
    U.el("div", { class: "overlay-bar" }, [barFill]),
    counter,
    legacyCounterMarker,
  ]);
  closeBtn.addEventListener("click", function () {
    API.call("overlay_action", "close").catch(fail);
  });

  // Escape key: dismiss the overlay.  Uses capture phase so Escape is
  // intercepted even if focus is inside the overlay panel.  The keydown
  // listener is attached to the document so it works regardless of which
  // element has focus.
  // Guard: document.addEventListener may not exist in node/JSDOM test harnesses.
  if (typeof document.addEventListener === "function") {
    document.addEventListener(
      "keydown",
      function (e) {
        if (e.key === "Escape" && !panel.classList.contains("hidden")) {
          API.call("overlay_action", "close").catch(fail);
        }
      },
      true,
    );
  }
  var panel = U.el("div", { class: "overlay-panel", testid: "overlay-panel" }, [
    head,
    loadingEl,
    bodyEl,
    progress,
  ]);
  view.appendChild(panel);

  // Karaoke colour stops + fade — a faithful port of overlay_paint.py
  // _word_appearance (PAST/FUTURE/PEAK RGB, smoothstep lerp, FADE_SECS),
  // identical to the public core frontend.
  var PAST = [0x60, 0x65, 0x7a],
    FUTURE = [0xc8, 0xcd, 0xe0],
    PEAK = [0xff, 0xff, 0xff],
    FADE_SECS = 0.5;
  function smoothstep(t) {
    t = t < 0 ? 0 : t > 1 ? 1 : t;
    return t * t * (3 - 2 * t);
  }
  function lerpRGB(a, b, t) {
    t = smoothstep(t);
    return (
      "rgb(" +
      Math.round(a[0] + (b[0] - a[0]) * t) +
      "," +
      Math.round(a[1] + (b[1] - a[1]) * t) +
      "," +
      Math.round(a[2] + (b[2] - a[2]) * t) +
      ")"
    );
  }
  function wordAppearance(i, cur, elapsed, w) {
    if (i === cur) return { color: "rgb(255,255,255)", cur: true };
    if (elapsed >= w.te) {
      var k = Math.max(0, 1 - (elapsed - w.te) / FADE_SECS);
      return { color: lerpRGB(PAST, PEAK, k), cur: false };
    }
    var k2 = Math.max(0, 1 - (w.ts - elapsed) / FADE_SECS);
    return { color: lerpRGB(FUTURE, PEAK, k2), cur: false };
  }

  var lastText = null;
  // Idle-aware polling: poll fast (~120ms) while reading/thinking/loading,
  // slow heartbeat (~2s) when idle.  A fast interval runs the engine_state
  // bridge call up to ~8 Hz during a read; at idle there is nothing to
  // update so we drop to ~0.5 Hz to avoid flooding the bridge worker.
  // _tickInterval holds the ACTIVE setInterval handle; _tickFast tracks
  // which rate is currently set so we only call setInterval when the rate
  // actually changes (avoids accumulating stacked intervals on every tick).
  var _tickInterval = null;
  var _tickFast = null; // true=fast, false=slow, null=none set yet

  var TICK_FAST_MS = 120;
  // TICK_SLOW_MS must be strictly less than OVERLAY_MESSAGE_MS (1800 ms) so
  // the slow idle heartbeat fires at least once during the "done" window of a
  // one-shot banner (e.g. "No text selected").  A 2000 ms idle poll misses the
  // entire 1800 ms window, leaving data-overlay-state stuck at "idle" and the
  // overlay panel never showing the message to the user.  1000 ms gives a
  // comfortable margin: the first slow tick always lands inside the 1800 ms
  // window, which then switches the poll to fast mode (120 ms) for the
  // remainder of the banner duration.
  var TICK_SLOW_MS = 1000;

  function _setTickRate(fast) {
    if (_tickFast === fast) return; // already at the right rate
    if (_tickInterval !== null) {
      clearInterval(_tickInterval);
    }
    _tickInterval = setInterval(tick, fast ? TICK_FAST_MS : TICK_SLOW_MS);
    _tickFast = fast;
  }

  function setVisible(vis) {
    panel.classList.toggle("hidden", !vis);
  }
  function tick() {
    API.call("engine_state")
      .then(function (s) {
        var st = s.overlay_state || "idle";
        document.body.setAttribute("data-overlay-state", st);
        var koff =
          parseInt(s.karaoke_offset_ms != null ? s.karaoke_offset_ms : 0, 10) /
          1000.0;
        if (st === "idle") {
          setVisible(false);
          loadingEl.classList.add("hidden");
          bodyEl.textContent = "";
          barFill.style.width = "0%";
          lastText = null;
          // Back off to slow heartbeat: nothing to update while idle.
          _setTickRate(false);
          return;
        }
        // Active state — ensure the fast poll rate is running so karaoke
        // and loading transitions are smooth.
        _setTickRate(true);
        setVisible(true);
        dot.className =
          "overlay-dot" +
          (st === "reading"
            ? " reading"
            : st === "thinking" || st === "loading"
              ? " thinking"
              : "");
        label.textContent =
          (s.brand_name || "PipPal") +
          (s.action_label ? "  ·  " + s.action_label : "");
        // Transport button disabled-states: prev/next stay enabled during
        // synthesis so rapid presses are delivered to the bridge even while
        // "thinking". Gate only on chunk-boundary (first/last). pause/replay
        // are reading-only (no audio to pause while synthesizing).
        // "loading" is the post-capture, pre-synth state — treat it like
        // "thinking" for nav so rapid prev/next are deliverable immediately.
        var isReading = st === "reading";
        var isNavigable = isReading || st === "thinking" || st === "loading";
        var prevDis = s.chunk_idx <= 0 || !isNavigable;
        var nextDis =
          s.chunk_total <= 1 ||
          s.chunk_idx >= s.chunk_total - 1 ||
          !isNavigable;
        var pauseDis = !isReading;
        prevBtn.disabled = prevDis;
        prevBtn.classList.toggle("disabled", prevDis);
        nextBtn.disabled = nextDis;
        nextBtn.classList.toggle("disabled", nextDis);
        pauseBtn.disabled = pauseDis;
        pauseBtn.classList.toggle("disabled", pauseDis);
        replayBtn.disabled = !isReading;
        replayBtn.classList.toggle("disabled", !isReading);
        // T2: Pause/play SVG icon driven by polled is_paused state.
        // Update the <path d> inside the button's SVG so the icon swaps
        // without destroying the SVG element or introducing unicode glyphs.
        var pbSvgPath = pauseBtn.querySelector("svg path");
        var pbIconKey = s.is_paused ? "play" : "pause";
        if (pbSvgPath) pbSvgPath.setAttribute("d", ICONS[pbIconKey]);
        pauseBtn.setAttribute("data-icon", pbIconKey);
        if (st === "reading" && s.chunk_text) {
          // Hide loading indicator once audio is playing; remove "dimmed"
          // so the new chunk's text is fully visible.
          loadingEl.classList.add("hidden");
          bodyEl.classList.remove("dimmed");
          if (s.chunk_text !== lastText) {
            lastText = s.chunk_text;
            bodyEl.innerHTML = "";
            s.words.forEach(function (w, i) {
              bodyEl.appendChild(
                U.el("span", {
                  class: "w",
                  "data-i": String(i),
                  text: w.word + " ",
                }),
              );
            });
          }
          var elapsed = (s.elapsed || 0) - koff,
            cur = -1;
          s.words.forEach(function (w, i) {
            if (elapsed >= w.ts) cur = i;
          });
          var spans = bodyEl.querySelectorAll(".w");
          for (var i = 0; i < spans.length; i++) {
            var ap = wordAppearance(i, cur, elapsed, s.words[i]);
            var sp = spans[i];
            sp.style.color = ap.color;
            sp.className = "w" + (ap.cur ? " cur" : "");
          }
          // Auto-follow: keep the active word in view inside the clamped
          // body without showing a scrollbar.  The scrollbar is hidden via
          // CSS (scrollbar-width:none + ::-webkit-scrollbar{display:none})
          // but overflow-y:auto still allows programmatic scrolling, so
          // scrollIntoView works and the user always sees the current word.
          var curSpan = bodyEl.querySelector(".cur");
          if (curSpan) {
            curSpan.scrollIntoView({ block: "nearest", inline: "nearest" });
          }
          var prog =
            s.chunk_duration > 0
              ? Math.max(0, Math.min(1, (s.elapsed || 0) / s.chunk_duration))
              : 0;
          barFill.style.width = (prog * 100).toFixed(1) + "%";
          counter.textContent =
            s.chunk_total > 1 ? s.chunk_idx + 1 + "/" + s.chunk_total : "";
          legacyCounterMarker.textContent = counter.textContent;
        } else if (st === "thinking" || st === "loading") {
          // Inject an in-body loader for every "thinking"/"loading" tick.
          // The loader is hidden event-driven when state transitions to
          // "reading". If action_label is set (not the generic placeholder),
          // show it; otherwise rotate the playful loading set.
          var explicit =
            s.action_label && s.action_label !== "Loading…"
              ? s.action_label
              : null;
          var loadingLabel = explicit || currentLoadingMessage();
          lastText = null;
          loadingEl.classList.add("hidden");
          bodyEl.classList.remove("dimmed");
          // Build the .reader-loading block once per state entry so the
          // shimmer animation is not restarted on every 120 ms tick.
          var labelSpan = bodyEl.querySelector(".reader-loading-label");
          if (!labelSpan) {
            bodyEl.innerHTML =
              '<div class="reader-loading">' +
              '<div class="reader-loading-bar"></div>' +
              '<span class="reader-loading-label" aria-live="polite">' +
              escapeLoadingText(loadingLabel) +
              "</span>" +
              "</div>";
          } else if (labelSpan.textContent !== loadingLabel) {
            labelSpan.textContent = loadingLabel;
          }
          barFill.style.width = "0%";
        } else if (st === "done" && s.overlay_message) {
          lastText = null;
          loadingEl.classList.add("hidden");
          bodyEl.textContent = s.overlay_message;
        } else {
          lastText = null;
          loadingEl.classList.add("hidden");
          bodyEl.textContent = "";
          barFill.style.width = "0%";
        }
      })
      .catch(function () {});
  }
  // Trigger-driven fast-kick: expose a guarded global so the
  // re-show path (window_lifecycle.py overlay branch) can call
  //   evaluate_js("window.__pippalOverlayKick && window.__pippalOverlayKick()")
  // immediately after show(). This forces _setTickRate(true) + a synchronous
  // tick() the instant the window reappears, without waiting for the next
  // slow 2000 ms poll to notice the new engine state.  The guard (&&) makes
  // it a no-op where the function may be absent.  The idle throttle is
  // unchanged: this only fires on an actual re-show, never while hidden.
  window.__pippalOverlayKick = function () {
    _setTickRate(true);
    tick();
  };

  // Start with a slow heartbeat so an idle launch doesn't flood the bridge.
  // The first tick() call will transition to fast rate if the engine is active.
  _setTickRate(false);
  tick();
  return Promise.resolve();
}

export function closeWin() {
  API.call("close_window").catch(function (e) {
    return handleCloseWindowFailure(t("errors.close_window"), e);
  });
}
