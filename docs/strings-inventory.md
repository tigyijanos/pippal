# Core string-extraction inventory (T-104 / issue #125)

Single source of truth: `webui/i18n/en.json` (English values are byte-identical to the pre-i18n literals). Both runtimes — the web-UI `window.t()` (`webui/js/i18n.js`) and the Python `pippal.i18n.t()` — read this catalog.

- Total catalog keys (excl. `_meta`): **186**
- `⟦key⟧` markers in any rendered surface: **0** (Tier-1 smoke `e2e/web/test_i18n_extraction_smoke.py`).
- Zero-regression: the pre-i18n suite passes UNCHANGED (no test file edited).

Width-constrained = short UI chrome (buttons, tray items, window titles, overlay loading lines, picker labels) where translations must respect a per-surface budget (enforced later by the T-303 width linter / T-106 overlay guard).

| Key | English value | Surface | Source | Width-constrained |
|---|---|---|---|---|
| `chrome.close` | Close | static chrome / titlebar | `webui/index.html` | yes |
| `footer.apply` | Apply | settings footer buttons | `webui/index.html` | yes |
| `footer.cancel` | Cancel | settings footer buttons | `webui/index.html` | yes |
| `footer.reset` | Reset to defaults | settings footer buttons | `webui/index.html` | yes |
| `footer.save` | Save | settings footer buttons | `webui/index.html` | yes |
| `confirm.no` | No | confirm modal buttons | `webui/index.html` | yes |
| `confirm.yes` | Yes | confirm modal buttons | `webui/index.html` | yes |
| `errors.close_settings` | Could not close settings window. | error toasts | `webui/js/{app-core,settings-footer,overlay}.js` | — |
| `errors.close_settings_after_save` | Could not close settings window after save. | error toasts | `webui/js/{app-core,settings-footer,overlay}.js` | — |
| `errors.close_window` | Could not close window. | error toasts | `webui/js/{app-core,settings-footer,overlay}.js` | — |
| `settings.lang.auto` | Auto (system) | settings · language card | `webui/js/settings-cards.js` | yes |
| `settings.lang.label` | Interface language | settings · language card | `webui/js/settings-cards.js` | yes |
| `settings.lang.saved` | Language saved — reload to apply. | settings · language card | `webui/js/settings-cards.js` | yes |
| `settings.lang.set_failed` | Failed to set language. | settings · language card | `webui/js/settings-cards.js` | yes |
| `settings.lang.title` | Language | settings · language card | `webui/js/settings-cards.js` | yes |
| `settings.lang.tray_hint` | Tray menu updates after restart. | settings · language card | `webui/js/settings-cards.js` | yes |
| `settings.voice.engine_label` | Engine | settings · voice card | `webui/js/settings.js` | yes |
| `settings.voice.hint_empty` | No Piper voice installed yet. Click Install voices to download one. | settings · voice card | `webui/js/settings.js` | yes |
| `settings.voice.hint_installed` | Piper voice. Click Manage to install more from the curated list. | settings · voice card | `webui/js/settings.js` | yes |
| `settings.voice.install_voices` | Install voices… | settings · voice card | `webui/js/settings.js` | yes |
| `settings.voice.manage` | Manage… | settings · voice card | `webui/js/settings.js` | yes |
| `settings.voice.none` | (no voice installed) | settings · voice card | `webui/js/settings.js` | yes |
| `settings.voice.title` | Voice | settings · voice card | `webui/js/settings.js` | yes |
| `settings.voice.voice_label` | Voice | settings · voice card | `webui/js/settings.js` | yes |
| `settings.speech.hint` | Speed: 0.6× clearer · 1.0× normal · 1.7× faster.   Variation: livelier intonation at higher values. | settings · speech card | `webui/js/settings.js` | — |
| `settings.speech.speed_label` | Speed | settings · speech card | `webui/js/settings.js` | — |
| `settings.speech.title` | Speech | settings · speech card | `webui/js/settings.js` | — |
| `settings.speech.variation_label` | Variation | settings · speech card | `webui/js/settings.js` | — |
| `settings.hotkeys.hint` | Format: windows+shift+r · ctrl+alt+space · alt+shift+f1 …  Captured combos are suppressed (other apps won't also see them). | settings · hotkeys card | `webui/js/settings.js` | — |
| `settings.hotkeys.title` | Hotkeys | settings · hotkeys card | `webui/js/settings.js` | — |
| `settings.panel.auto_hide_label` | Auto-hide delay | settings · reader panel | `webui/js/settings.js` | yes |
| `settings.panel.auto_hide_unit` | ms | settings · reader panel | `webui/js/settings.js` | yes |
| `settings.panel.distance_label` | Distance from taskbar | settings · reader panel | `webui/js/settings.js` | yes |
| `settings.panel.distance_unit` | px | settings · reader panel | `webui/js/settings.js` | yes |
| `settings.panel.karaoke_label` | Karaoke offset | settings · reader panel | `webui/js/settings.js` | yes |
| `settings.panel.karaoke_unit` | ms (positive = highlight waits, negative = highlight leads) | settings · reader panel | `webui/js/settings.js` | yes |
| `settings.panel.show_overlay` | Show panel while reading | settings · reader panel | `webui/js/settings.js` | yes |
| `settings.panel.show_text` | Show text with karaoke highlight | settings · reader panel | `webui/js/settings.js` | yes |
| `settings.panel.title` | Reader panel | settings · reader panel | `webui/js/settings.js` | yes |
| `settings.integration.hint` | Adds a 'Read with PipPal' entry to the right-click menu of .txt and .md files in File Explorer (current user only). | settings · Windows integration | `webui/js/{settings,settings-footer}.js` | — |
| `settings.integration.install` | Install | settings · Windows integration | `webui/js/{settings,settings-footer}.js` | — |
| `settings.integration.installed_toast` | Right-click entry installed for .txt and .md. | settings · Windows integration | `webui/js/{settings,settings-footer}.js` | — |
| `settings.integration.remove` | Remove | settings · Windows integration | `webui/js/{settings,settings-footer}.js` | — |
| `settings.integration.status_all` | ✓ Right-click entry installed for .txt and .md. | settings · Windows integration | `webui/js/{settings,settings-footer}.js` | — |
| `settings.integration.status_none` | ○ Right-click entry not installed. | settings · Windows integration | `webui/js/{settings,settings-footer}.js` | — |
| `settings.integration.status_partial` | ⚠ Partial install — re-run Install to fix. | settings · Windows integration | `webui/js/{settings,settings-footer}.js` | — |
| `settings.integration.title` | Windows integration | settings · Windows integration | `webui/js/{settings,settings-footer}.js` | — |
| `settings.notices.hint` | PipPal uses open-source libraries and local TTS runtime artifacts. Their licences are included with this install or source checkout. | settings · notices card | `webui/js/settings.js` | — |
| `settings.notices.title` | Open-source notices | settings · notices card | `webui/js/settings.js` | — |
| `settings.notices.view` | View licences… | settings · notices card | `webui/js/settings.js` | — |
| `settings.about.copyright` | © 2026 Bug Factory Kft.  ·  Offline-first by design. | settings · about card | `webui/js/settings.js` | — |
| `settings.about.tagline` | Your little offline reading buddy. | settings · about card | `webui/js/settings.js` | — |
| `settings.about.title` | About | settings · about card | `webui/js/settings.js` | — |
| `settings.reset.confirm_body` | Reset every field to its built-in default? Click Apply or Save afterwards to keep them. | settings · reset flow | `webui/js/settings-footer.js` | — |
| `settings.reset.confirm_title` | Reset to defaults | settings · reset flow | `webui/js/settings-footer.js` | — |
| `settings.reset.toast` | Reset to defaults — click Apply or Save to keep them. | settings · reset flow | `webui/js/settings-footer.js` | — |
| `settings.save.applied` | Applied. | settings · save toasts | `webui/js/settings-footer.js` | — |
| `settings.save.hotkey_fail` | Saved, but some hotkeys could not be bound. | settings · save toasts | `webui/js/settings-footer.js` | — |
| `settings.save.saved` | Saved. | settings · save toasts | `webui/js/settings-footer.js` | — |
| `settings.diag.confirm_body` | Delete all diagnostics logs? This cannot be undone. | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.confirm_title` | Delete diagnostics logs | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.delete` | Delete logs | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.delete_failed` | Delete failed. | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.deleted` | (plural on `count`) one="Deleted {count} log file.", other="Deleted {count} log files." | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.folder_default` | local PipPal folder | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.folder_toast` | Log folder: {folder} | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.level.error` | Errors only | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.level.off` | Off | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.level.trace` | Full trace | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.level_label` | Log level | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.level_set` | Diagnostics level set to “{level}”. | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.notice` | Diagnostics logs help the creator fix bugs. <strong>Your reading text is never logged</strong> — only technical metadata (sizes, formats, timings, and error types). Logs stay on your computer. Off keeps logging disabled; Errors only records failures; Full trace records detailed step-by-step events for harder bugs. | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.open` | Open log folder | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.set_level_failed` | Failed to set level. | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.status` | (plural on `count`) one="{count} log file  ·  {kb} KB  ·  {folder}", other="{count} log files  ·  {kb} KB  ·  {folder}" | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `settings.diag.title` | Diagnostics | settings · diagnostics | `webui/js/settings-cards.js` | — |
| `promo.get_pro` | Get PipPal Pro | settings · Pro promo | `webui/js/settings.js` | yes |
| `promo.headline` | Unlock PipPal Pro | settings · Pro promo | `webui/js/settings.js` | yes |
| `promo.sub` | AI summaries, premium neural voices, document import, and more. | settings · Pro promo | `webui/js/settings.js` | yes |
| `onboarding.title.missing_piper` | PipPal needs a local reading engine | onboarding · headings | `webui/js/onboarding.js` | — |
| `onboarding.title.missing_voice` | PipPal needs a local voice | onboarding · headings | `webui/js/onboarding.js` | — |
| `onboarding.title.ready` | PipPal is ready to read locally | onboarding · headings | `webui/js/onboarding.js` | — |
| `onboarding.subtitle.missing_piper` | The tray app is running so you can repair setup or switch engines. | onboarding · subheadings | `webui/js/onboarding.js` | — |
| `onboarding.subtitle.missing_voice` | Install an offline voice before the first reading test.
No account. No telemetry. No cloud TTS. | onboarding · subheadings | `webui/js/onboarding.js` | — |
| `onboarding.subtitle.ready` | PipPal reads selected text aloud on this PC.
No account. No telemetry. No cloud TTS.
Let's make sure you can hear it now. | onboarding · subheadings | `webui/js/onboarding.js` | — |
| `onboarding.status.done` | Done. PipPal can read selected text on this PC. | onboarding · status | `webui/js/onboarding.js` | — |
| `onboarding.card.try_it` | Try it in any app | onboarding · cards | `webui/js/onboarding.js` | — |
| `onboarding.card.voice_check` | Local voice check | onboarding · cards | `webui/js/onboarding.js` | — |
| `onboarding.voice_label` | Voice: {label} | onboarding · labels | `webui/js/onboarding.js` | yes |
| `onboarding.hotkey_label` | Hotkey: {label} | onboarding · labels | `webui/js/onboarding.js` | yes |
| `onboarding.try_hint` | Select text in a browser, PDF, document, or this box. | onboarding · hint | `webui/js/onboarding.js` | — |
| `onboarding.btn.close` | Close | onboarding · buttons | `webui/js/onboarding.js` | yes |
| `onboarding.btn.finish` | Finish setup | onboarding · buttons | `webui/js/onboarding.js` | yes |
| `onboarding.btn.install_voice` | Install default voice | onboarding · buttons | `webui/js/onboarding.js` | yes |
| `onboarding.btn.open_settings` | Open Settings | onboarding · buttons | `webui/js/onboarding.js` | yes |
| `onboarding.btn.open_setup` | Open setup instructions | onboarding · buttons | `webui/js/onboarding.js` | yes |
| `onboarding.btn.open_vm` | Open Voice Manager | onboarding · buttons | `webui/js/onboarding.js` | yes |
| `onboarding.btn.play` | Play sample | onboarding · buttons | `webui/js/onboarding.js` | yes |
| `onboarding.btn.play_again` | Play sample again | onboarding · buttons | `webui/js/onboarding.js` | yes |
| `onboarding.btn.skip` | Skip for now | onboarding · buttons | `webui/js/onboarding.js` | yes |
| `onboarding.install.cancelled` | Install cancelled. | onboarding · install status | `webui/js/onboarding.js` | — |
| `onboarding.install.failed` | Install failed. | onboarding · install status | `webui/js/onboarding.js` | — |
| `onboarding.install.starting` | Starting… | onboarding · install status | `webui/js/onboarding.js` | — |
| `onboarding.play_first` | Play the sample first, then confirm you heard it. | onboarding · sample status | `webui/js/onboarding.js` | — |
| `onboarding.playing` | Playing sample. If you can hear it, finish setup. | onboarding · sample status | `webui/js/onboarding.js` | — |
| `onboarding.playing_again` | Playing sample again. PipPal is already set up. | onboarding · sample status | `webui/js/onboarding.js` | — |
| `onboarding.hotkey.not_configured` | Not configured | onboarding · hotkey label (py) | `src/pippal/onboarding.py` | yes |
| `onboarding.sample_hotkey_default` | the read hotkey | onboarding · sample text (py, spoken) | `src/pippal/onboarding.py` | — |
| `onboarding.sample_text` | PipPal is reading locally. Select text anywhere, then press {hotkey}. | onboarding · sample text (py, spoken) | `src/pippal/onboarding.py` | — |
| `onboarding.readiness.engine_missing` | Piper engine: missing | onboarding · readiness (py) | `src/pippal/onboarding.py` | — |
| `onboarding.readiness.engine_ready` | Piper engine: ready | onboarding · readiness (py) | `src/pippal/onboarding.py` | — |
| `onboarding.readiness.engine_selected_label` | managed by selected engine | onboarding · readiness (py) | `src/pippal/onboarding.py` | — |
| `onboarding.readiness.engine_selected_ready` | Ready to test the selected reading engine. | onboarding · readiness (py) | `src/pippal/onboarding.py` | — |
| `onboarding.readiness.missing_piper` | The local Piper engine is missing. Run setup.ps1 from this checkout, or switch to another engine in Settings. Reading is paused until a local engine is ready. | onboarding · readiness (py) | `src/pippal/onboarding.py` | — |
| `onboarding.readiness.missing_voice` | No local voice is installed yet. Install the default English voice so PipPal can speak offline. Download size: about 120 MB. | onboarding · readiness (py) | `src/pippal/onboarding.py` | — |
| `onboarding.readiness.ready` | Local voice check is ready. | onboarding · readiness (py) | `src/pippal/onboarding.py` | — |
| `onboarding.readiness.voice_not_installed` | not installed | onboarding · readiness (py) | `src/pippal/onboarding.py` | — |
| `onboarding.recovery` | {failure} To retry, select text and press {hotkey} again. If that app blocks copying, try a browser, document, or text field, or use Play sample. | onboarding · recovery msg (py) | `src/pippal/onboarding.py` | — |
| `overlay.loading.breathe` | Teaching the narrator to breathe… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.brewing` | Brewing a fresh batch of phonemes… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.buffering` | Buffering a little eloquence… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.calibrating` | Calibrating the storyteller… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.intonation` | Gathering the right intonation… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.pauses` | Rehearsing the dramatic pauses… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.polishing` | Polishing the consonants… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.reticulating` | Reticulating syllables… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.smoothing` | Smoothing out the syllables… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.summoning` | Summoning the perfect voice… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.tuning` | Tuning the inner monologue… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.untangling` | Untangling the sentences… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.vowels` | Coaxing vowels into formation… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `overlay.loading.warmup` | Warming up the vocal cords… | overlay · loading lines (T-106 width guard) | `webui/js/overlay.js` | yes |
| `voices.action.cancel` | Cancel | voice manager surface | `webui/js/voices.js` | yes |
| `voices.action.install` | Install | voice manager surface | `webui/js/voices.js` | yes |
| `voices.action.remove` | Remove | voice manager surface | `webui/js/voices.js` | yes |
| `voices.empty` | No voices match. Clear the filter to see everything. | voice manager surface | `webui/js/voices.js` | yes |
| `voices.filter.all_langs` | All languages | voice manager surface | `webui/js/voices.js` | yes |
| `voices.filter.lang_label` | Language | voice manager surface | `webui/js/voices.js` | yes |
| `voices.filter.quality_any` | Any | voice manager surface | `webui/js/voices.js` | yes |
| `voices.filter.quality_label` | Quality | voice manager surface | `webui/js/voices.js` | yes |
| `voices.filter.search_label` | Search | voice manager surface | `webui/js/voices.js` | yes |
| `voices.filter.status_any` | Any | voice manager surface | `webui/js/voices.js` | yes |
| `voices.filter.status_installed` | Installed | voice manager surface | `webui/js/voices.js` | yes |
| `voices.filter.status_label` | Status | voice manager surface | `webui/js/voices.js` | yes |
| `voices.filter.status_not_installed` | Not installed | voice manager surface | `webui/js/voices.js` | yes |
| `voices.remove.confirm_body` | Remove {label}? | voice manager surface | `webui/js/voices.js` | yes |
| `voices.remove.confirm_title` | Remove voice | voice manager surface | `webui/js/voices.js` | yes |
| `voices.row.meta` | id: {id}   ·   {quality} | voice manager surface | `webui/js/voices.js` | yes |
| `voices.status.failed` | failed | voice manager surface | `webui/js/voices.js` | yes |
| `voices.status.installed` | ✓ installed | voice manager surface | `webui/js/voices.js` | yes |
| `voices.status.removing` | removing… | voice manager surface | `webui/js/voices.js` | yes |
| `voices.toast.cancelling` | Cancelling… | voice manager surface | `webui/js/voices.js` | yes |
| `voices.toast.install_cancelled` | Voice install cancelled. | voice manager surface | `webui/js/voices.js` | yes |
| `voices.toast.install_failed` | Voice install failed: {error} | voice manager surface | `webui/js/voices.js` | yes |
| `voices.toast.installed` | Voice installed — open Settings to make it your active voice. | voice manager surface | `webui/js/voices.js` | yes |
| `voices.toast.installed_plain` | Voice installed. | voice manager surface | `webui/js/voices.js` | yes |
| `voices.unknown_error` | unknown error | voice manager surface | `webui/js/voices.js` | yes |
| `voices.window_title` | Voices | voice manager surface | `webui/js/voices.js` | yes |
| `notices.window_title` | PipPal - Open-source licences | notices · window brand | `webui/js/notices.js` | yes |
| `notices.not_found` | Open-source notices were not found.

Please reinstall PipPal to restore the licences file, or open docs/THIRD_PARTY.md from the source checkout. | notices · fallback text (py) | `src/pippal/web_ui/bridge.py` | — |
| `notices.read_error` | Could not read {path}

{error} | notices · fallback text (py) | `src/pippal/web_ui/bridge.py` | — |
| `about.link.github` | GitHub | about links (py) | `src/pippal/web_ui/bridge.py` | yes |
| `about.link.licence` | Licence (MIT) | about links (py) | `src/pippal/web_ui/bridge.py` | yes |
| `about.link.privacy` | Privacy | about links (py) | `src/pippal/web_ui/bridge.py` | yes |
| `about.link.reddit` | Community (Reddit) | about links (py) | `src/pippal/web_ui/bridge.py` | yes |
| `about.link.terms` | Terms | about links (py) | `src/pippal/web_ui/bridge.py` | yes |
| `about.link.website` | Website | about links (py) | `src/pippal/web_ui/bridge.py` | yes |
| `voice.status.cancelled` | Cancelled. | voice install status (py) | `src/pippal/web_ui/bridge.py` | — |
| `voice.status.done` | ✓ Done. | voice install status (py) | `src/pippal/web_ui/bridge.py` | — |
| `voice.status.downloading` | Downloading {label}… | voice install status (py) | `src/pippal/web_ui/bridge.py` | — |
| `voice.status.downloading_default` | Downloading default voice… | voice install status (py) | `src/pippal/web_ui/bridge.py` | — |
| `voice.status.failed` | Failed: {error} | voice install status (py) | `src/pippal/web_ui/bridge.py` | — |
| `voice.status.starting` | Starting… | voice install status (py) | `src/pippal/web_ui/bridge.py` | — |
| `tray.clear_history` | Clear history | system tray menu/tooltip (py) | `src/pippal/web_ui/app_web.py` | yes |
| `tray.first_run_check` | First-run check | system tray menu/tooltip (py) | `src/pippal/web_ui/app_web.py` | yes |
| `tray.quit` | Quit | system tray menu/tooltip (py) | `src/pippal/web_ui/app_web.py` | yes |
| `tray.recent` | Recent | system tray menu/tooltip (py) | `src/pippal/web_ui/app_web.py` | yes |
| `tray.recent_empty` | (empty) | system tray menu/tooltip (py) | `src/pippal/web_ui/app_web.py` | yes |
| `tray.settings` | Settings… | system tray menu/tooltip (py) | `src/pippal/web_ui/app_web.py` | yes |
| `tray.tooltip_speaking` | {brand} — speaking | system tray menu/tooltip (py) | `src/pippal/web_ui/app_web.py` | yes |
| `toast.startup.title` | Running in the background | startup tray balloon (py) | `src/pippal/web_ui/startup_toast.py` | yes |
| `window.notices.title` | PipPal - Open-source licences | native window titles (py) | `src/pippal/web_ui/window_lifecycle.py` | yes |
| `window.onboarding.title` | PipPal | native window titles (py) | `src/pippal/web_ui/window_lifecycle.py` | yes |
| `window.overlay.title` | PipPal | native window titles (py) | `src/pippal/web_ui/window_lifecycle.py` | yes |
| `window.settings.title` | PipPal | native window titles (py) | `src/pippal/web_ui/window_lifecycle.py` | yes |
| `window.voices.title` | Voices | native window titles (py) | `src/pippal/web_ui/window_lifecycle.py` | yes |

## Deliberately NOT extracted (kept English by design)

| Literal | Location | Reason |
|---|---|---|
| `NO_VOICE_SCRIPT` (karaoke onboarding script) | `src/pippal/onboarding.py` | Paired with an English WAV recording (design §1 locked). |
| `SELECTED_TEXT_CAPTURE_FAILURE = "No selected text was captured."` | `src/pippal/onboarding.py` | Cross-module STATUS SENTINEL compared by value in `engine.py` + tests; surfaced only wrapped by `onboarding.recovery` (which IS keyed, with a `{failure}` placeholder). |
| `"Loading…"` sentinel comparison | `webui/js/overlay.js` | Protocol constant (`action_label === "Loading…"` means "generic placeholder"); never displayed — replaced by a whimsical `overlay.loading.*` line. |
| `"PipPal"` brand text | `index.html`, `overlay.js`, tray/window titles | Product brand (glossary: keep English). Window titles ARE keyed (`window.*`) but resolve to `"PipPal"`. |
| Piper quality codes (`high`/`medium`/`low`/`x_low`), key-name labels (`Ctrl`/`Shift`/…) | `voices.js`, `onboarding.py` | Technical identifiers / keyboard key names, not prose. |
| Internal exception messages (`unknown voice: …`, `empty response for …`, `task not found`) | `bridge.py` | Diagnostic exception text, not a primary UI surface. |
