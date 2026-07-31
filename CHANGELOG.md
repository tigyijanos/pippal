# PipPal Changelog

## 0.3.2 - 2026-07-31

Release date: 2026-07-31

- Security: hardens the local loopback web bridge while preserving legitimate
  same-origin browser requests and Origin-less native JSON clients.

## 0.3.1 - 2026-07-21

Release date: 2026-07-21

- Upgrade compatibility: keeps the complete Ryan voice selected for users
  upgrading from 0.3.0 when the new default voice is not installed. Explicit
  voice selections continue to win.
- Localization: adds the language picker and localized catalogs for German,
  Hungarian, Portuguese (Brazil), Simplified Chinese, Ukrainian, and English,
  with persisted startup language and plural handling in Python and JavaScript.
- Voice setup: installs the default voice for the selected UI language and
  localizes Voice Manager language and quality labels.
- LibriTTS: exposes the model's multi-speaker catalog so compatible clients
  can offer hundreds of English speaker choices from one installed voice.
- Reading UI: handles CJK karaoke segmentation and removes remaining hard-coded
  overlay and hotkey labels from localized surfaces.
- Voice licensing: uses public-domain LJSpeech as the English default for new
  installations and removes non-commercial voices from the built-in catalog.
- Packaging: aligns package, application, installer, and manual release-workflow
  metadata on 0.3.1. The workflow uploads only to an existing `v0.3.1` release.

## 0.3.0 - 2026-06-28

Release date: 2026-06-28

- Reworked the reader, overlay, onboarding, and Settings surfaces around the
  web UI architecture shipped by the `v0.3.0` tag.
- Fixed pause/resume timing, forward/back navigation, loading-state ordering,
  and reading-state updates across chunk boundaries.
- Added local diagnostic collection and its Settings surfaces, including
  privacy and non-blocking regression coverage.
- Restored the startup tray notification and expanded release-critical UI,
  playback, window-lifecycle, and packaged-data test coverage.

## 0.2.4 - 2026-05-15

Release date: 2026-05-15

Categories:

- Onboarding: added a first-run activation panel that guides a new user
  from setup to a real sample playback before setup can be completed.
- Voice setup: the first-run Voice Manager path opens on the recommended
  Ryan voice, returns to the activation panel after install, and keeps the
  voice list scrollable over row content.
- UI consistency: Settings-adjacent dialogs now use the shared native
  Windows title bar, dark dialog body, and centered placement instead of
  custom internal headers or top-left fallback placement.
- Selected text reliability: improved the Notepad selected-text capture
  path and documented the current compatibility evidence without broad
  "anywhere" claims.
- Safety and release gates: production command-server control routes stay
  hidden unless the explicit E2E harness enables them, and live UI evidence
  capture is now part of the release-readiness story.

## 0.2.3 - 2026-05-13

Release date: 2026-05-13

Categories:

- Reliability: fixed atomic single-instance startup, isolated playback
  temporary chunks per session, and improved settings-window reopen
  behavior.
- UI consistency: added the core open-source notices viewer to Settings
  and stabilized chromeless dialog placement and dragging.
- Voice readiness: validates configured Piper voice files before use,
  encodes Voice Manager download URLs, and caps unbroken text chunks.
- Hotkeys and launch surface: rejects duplicate hotkey combinations,
  fixes context-menu helper import paths, portable launchers, package
  asset runtime paths, and setup default voice paths.
- Recent history: command-server and file-open read requests now appear
  in the Recent tray menu after successful playback starts.
- QA: adds install-surface smoke coverage and regression tests for the
  release-critical startup, voice, context-menu, playback, settings,
  and launcher paths.

## 0.2.0 - Public release

Release date: 2026-05-11

- Released the public PipPal core as the open-source Community edition.
- Included the reader panel, Windows tray app, settings UI, hotkeys,
  Piper voice support, and local smoke/test coverage.
- Kept paid-edition features out of the public package; Store builds
  are maintained separately.
