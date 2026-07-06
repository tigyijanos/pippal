# PipPal Core - First-Run Activation Design

Issue: [#44](https://github.com/bug-factory-kft/pippal/issues/44)

Target release branch: `release/0.2.4`

Goal: a new Core user should hear selected text through PipPal within
60 seconds of launching the app for the first time.

This is a design and implementation-breakdown artifact. It does not
define a Pro upsell, account step, telemetry event, cloud service, or
new TTS backend.

## Current Baseline

- `setup.ps1` can provision the local Piper binary, Python
  dependencies, and the default `en_US-ljspeech-high` voice.
- The app already uses the tray, Settings window, Voice Manager,
  overlay, and global hotkey architecture needed for activation.
- When the selected backend has no usable voice, the engine can play a
  bundled no-voice onboarding WAV with the normal reader overlay.
- If Piper is selected and `piper.exe` is missing, startup currently
  exits before the user sees an in-app repair path.

## Activation Principles

- Prove the core value before advanced configuration: local text to
  local speech.
- Keep the promise visible: no account, no telemetry, no cloud TTS.
- Prefer the default voice when it is already installed; do not force
  a voice-shopping decision before the first successful read.
- Fail with a next action, not a dead end.
- Mark activation complete only after the user hears either the sample
  sentence or their selected text, and keep the real hotkey visible.

## 60-Second Flow

Timer starts when the tray app first opens and the first-run activation
state has not been completed for the current user data directory.

| Time | App state | User action | Success criteria |
| --- | --- | --- | --- |
| 0-5 s | Compact first-run panel opens above the tray or as a small Tk dialog. | User sees privacy promise and local readiness check. | Panel is visible without opening Settings manually. |
| 5-15 s | App checks Piper binary, installed voices, and hotkey binding. | User clicks `Start` if all checks pass. | No Pro, account, or telemetry step appears. |
| 15-30 s | If default voice is present, play sample immediately. If missing but Piper exists, offer one-button default voice install. | User clicks `Install default voice` only when needed. | Sample playback starts as soon as a usable voice is available. |
| 30-45 s | Panel shows the active read hotkey and a short practice sentence. | User selects the practice text or text in another app. | The exact configured hotkey is visible. |
| 45-60 s | User presses the hotkey. | User hears their selected text, and the overlay confirms success. | Activation is marked complete after successful read or explicit sample success fallback. |

The fast path is:

1. Launch PipPal.
2. See: local-only promise and ready checks.
3. Hear a sample sentence from the installed default voice.
4. See the active hotkey.
5. Select text that the focused app can copy and press the hotkey.
6. Hear the selected text.

## Screens And Copy

### Screen 1: Welcome And Privacy

Title: `PipPal is ready to read locally`

Body:

```text
PipPal reads selected text aloud on this PC.
No account. No telemetry. No cloud TTS.
Let's make sure you can hear it now.
```

Primary button: `Start`

Secondary button: `Skip for now`

Footer:

```text
You can reopen this from the tray menu: First-run check.
```

### Screen 2: Local Readiness

Title: `Local voice check`

Ready state:

```text
Piper engine: ready
Voice: en_US-ljspeech-high
Hotkey: Win+Shift+R
```

Primary button: `Play sample`

Missing voice state:

```text
No local voice is installed yet.
Install the default English voice so PipPal can speak offline.
Download size: about 120 MB.
```

Primary button: `Install default voice`

Secondary button: `Open Voice Manager`

Missing Piper state:

```text
The local Piper engine is missing.
Run setup.ps1 from this checkout, then open PipPal again.
```

Primary button: `Open setup instructions`

Secondary button: `Close`

### Screen 3: Sample Playback

Title: `PipPal is ready to read locally`

Sample text:

```text
PipPal is reading locally. Select text in an app that can copy it, then press Win+Shift+R.
```

Initial state:

- `Finish setup` is disabled until a sample is played.
- `Open Settings` remains available for voice or hotkey changes.

During playback:

```text
Playing sample. If you can hear it, finish setup.
```

Primary button after sample playback: `Finish setup`

Secondary button after sample playback: `Play sample again`

After `Finish setup`:

```text
Done. PipPal can read selected text on this PC.
```

Primary button: `Play sample`

Completion button: `Finish setup`

There is no separate `No sound` button in the current Core UI. If the
sample is not audible, the user can replay it, open Settings, or skip
and return through the tray's First-run check entry.

### Screen 4: Try Real Text

Title: `Try real selected text`

Body:

```text
Select text in a browser, document, or this box where normal Ctrl+C works.
Then press Win+Shift+R.
```

Practice text:

```text
This is my first PipPal read.
```

Success state:

```text
Done. PipPal can read selected text on this PC.
```

Primary button: `Finish`

Secondary button: `Open Settings`

## Failure States

| Failure | Detection | User copy | Recovery |
| --- | --- | --- | --- |
| No Piper binary | Selected engine is `piper` and `PIPER_EXE` does not exist. | `The local Piper engine is missing. Run setup.ps1 from this checkout, then open PipPal again.` | Link to README setup section; keep app from silently exiting in the implementation follow-up. |
| No voice installed | `installed_voices()` is empty for Piper. | `No local voice is installed yet. Install the default voice so PipPal can speak offline.` | One-button install of default voice; fallback to Voice Manager. |
| Voice download fails | Default voice install raises network, permission, or partial-file error. | `The voice download did not finish. Check your connection or choose a voice later in Voice Manager.` | Delete partial files, keep retry button, keep app usable for settings/repair. |
| Hotkey conflict | Binding the configured read hotkey fails or duplicate combo validation reports conflict. | `Win+Shift+R is already taken. Choose another read hotkey before the final test.` | Open Hotkeys card inline or deep-link Settings > Hotkeys. |
| Clipboard denied or unchanged | Capture returns no text after the user presses the read hotkey. | `PipPal could not read the current selection. Try Ctrl+C once, then press the hotkey again.` | Offer retry, practice text box, and clipboard troubleshooting link. |
| No sound heard | Sample playback completes but user does not finish setup. | `Playing sample. If you can hear it, finish setup.` | Replay sample, open Settings, or skip and return later; do not mark activation complete. |
| User skips | User clicks `Skip for now`. | `No problem. PipPal will stay in the tray. Use First-run check when you want to test it.` | Do not mark activation complete; show tray menu entry until success. |

## State Model

Use a small activation state separate from normal user preferences:

```json
{
  "first_run_activation": {
    "completed_at": "2026-05-14T18:00:00Z",
    "completed_with": "selected_text",
    "last_failure": null
  }
}
```

Completion rules:

- `completed_with = "selected_text"` when the hotkey path captures
  non-empty text and playback starts.
- `completed_with = "sample"` only when the user confirms they heard
  the sample and skips the real-text test.
- Do not complete on dialog close, sample start, voice install, or
  opening Settings.

## Implementation Breakdown

The work should be split because it crosses startup, UI, voice
download, hotkey binding, and manual validation.

1. `Implement Core first-run activation panel`
   - Add a small Tk activation panel that can be launched on first
     run and from the tray.
   - Show privacy copy, local readiness, active hotkey, and practice
     text.
   - Keep it Core-only and independent of extension packages.

2. `Add one-click default voice install for first-run activation`
   - Reuse Voice Manager download primitives or extract a shared
     default-voice installer.
   - Show progress, partial-file cleanup, retry, and Voice Manager
     fallback.
   - Preserve the existing `setup.ps1` path for source installs.

3. `Replace first-run hard exits with in-app repair states`
   - When Piper is selected but missing, show a repair screen instead
     of exiting before UI.
   - Keep alternative registered engines unaffected.
   - Include tests for the readiness decision where possible.

4. `Add activation hotkey and clipboard failure recovery`
   - Surface hotkey bind conflicts inside the activation flow.
   - Detect empty clipboard capture during the practice step.
   - Add retry and Settings > Hotkeys repair paths.

5. `Add first-run activation validation coverage`
   - Add focused tests for activation state transitions and readiness
     classification.
   - Add a manual clean-data-dir walkthrough for UI/audio behavior.

## Acceptance Checks

Manual clean profile:

```powershell
$env:PIPPAL_DATA_DIR = "$env:TEMP\PipPal-first-run-check"
Remove-Item -Recurse -Force $env:PIPPAL_DATA_DIR -ErrorAction SilentlyContinue
.\setup.ps1
pythonw reader_app.py
```

Expected:

- First-run panel appears without opening Settings manually.
- Privacy copy is visible before any optional configuration.
- Default voice path can reach sample playback.
- The active hotkey shown in the panel matches the configured read
  hotkey.
- Selecting the practice sentence and pressing the hotkey starts
  speech within 60 seconds on a typical broadband connection where the
  default voice is not already cached.
- No account, telemetry prompt, cloud TTS prompt, or Pro-only gate
  appears.

Failure walkthroughs:

- Rename or remove `piper\piper.exe`; launch shows missing-Piper
  repair copy.
- Start with an empty `voices` directory; launch shows default voice
  install copy.
- Force a hotkey conflict; activation points to hotkey repair before
  the final test.
- Press the hotkey with no selected text; activation shows clipboard
  recovery and retry.

Relevant command checks after implementation:

```powershell
python -m pytest tests\test_onboarding.py tests\test_voice_manager.py tests\test_hotkey.py -q
python -m ruff check .
```

If a named test file does not exist yet, the implementation issue that
introduces behavior should add the smallest focused test for its pure
logic. UI/audio behavior remains a manual walkthrough unless a stable
headless harness is introduced.

## Open Questions For Implementation

- Should the activation state live in `config.json` or a separate
  first-run file under `PIPPAL_DATA_DIR`? A separate file avoids
  mixing a milestone event with ordinary preferences, but config keeps
  persistence simpler.
- Should source installs auto-run the default voice installer from the
  panel, or should the panel only point back to `setup.ps1`? Auto-run
  is faster for users, but shared download code must avoid duplicating
  setup logic.
- Should the tray keep a permanent `First-run check` item after
  success? Keeping it helps support, but a permanent item adds menu
  weight for daily use.

## Learning Note

This document uses an activation funnel: a short, testable path from
launch to first value. The pattern is common in desktop apps because
install success is not the same as user success. It was chosen over a
README-only quickstart because the risk is runtime friction, not just
missing documentation. Alternatives are a full setup wizard or silent
auto-configuration. The tradeoff is more UI work later, but clearer
failure handling and stronger release acceptance now.
