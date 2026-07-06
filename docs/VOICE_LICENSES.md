# Voice licenses (Piper TTS)

This document records the dataset license and model lineage of every voice
PipPal ships as a **language default**, plus the rationale for voices that were
deliberately **removed** from the offered catalog. It is the licensing source of
truth referenced by issue #157.

Sources: the per-voice `MODEL_CARD` files under
`huggingface.co/rhasspy/piper-voices` (verified 2026-07-07) and the
2026-07-07 license-research memo cited in #157.

## Why this matters

PipPal is a paid application. A default voice whose **dataset** carries a
non-commercial (NC) or research-only license is not acceptable to ship as the
out-of-the-box default. The EN default was therefore moved off `en_US-ryan-high`
(CC BY-NC-SA 4.0 dataset) onto `en_US-ljspeech-high` (public domain).

## Per-default-voice license table

| UI lang | Default voice id       | Dataset | Dataset license | Model lineage | Verdict |
|---------|------------------------|---------|-----------------|---------------|---------|
| en      | `en_US-ljspeech-high`  | LJ Speech | **Public domain** | Trained from scratch | Clean — commercial-safe |
| de      | `de_DE-thorsten-high`  | Thorsten-Voice | **CC0** | Finetuned from U.S. English lessac | CC0 data; see lessac-lineage note |
| hu      | `hu_HU-anna-medium`    | OHF-Voice voice-datasets | **CC0** | Finetuned from U.S. English lessac | GRAY (lessac-derived) — PO-accepted |
| uk      | `uk_UA-ukrainian_tts-medium` | OHF-Voice voice-datasets | **CC0** | Trained from scratch | Clean — commercial-safe |
| pt-BR   | `pt_BR-faber-medium`   | OHF-Voice voice-datasets | **CC0** | Finetuned from U.S. English lessac | GRAY (lessac-derived) — PO-accepted |
| zh-CN   | `zh_CN-huayan-medium`  | HuaYan_TTS | **Unknown** | Finetuned from U.S. English lessac | GRAY (Unknown license + lessac-derived) — PO-accepted as download-only default; see note |

### lessac-derivative gray-zone note (hu, pt-BR, de, zh)

Several Piper voices are *model-finetuned* from the U.S. English **lessac** voice
(whose training corpus, Blizzard-2013, is research-only). The **datasets** used to
finetune hu/pt-BR/de/uk are themselves CC0, but the resulting model weights carry
a lineage from lessac. The PO has **accepted this gray zone** for `hu_HU-anna` and
`pt_BR-faber` as language defaults: they are the only reasonable-quality Piper
voices for those languages, the training data is CC0, and the derivative-weights
question is legally unsettled rather than a clear NC restriction. This decision is
documented here as required by #157.

### zh-CN huayan — verification finding + PO decision (#157)

`zh_CN-huayan-medium` was verified against its HF `MODEL_CARD`:

- Dataset: <https://github.com/PlayVoice/HuaYan_TTS>
- **Dataset license: Unknown**
- Model lineage: **finetuned from the U.S. English lessac voice** (medium).

This is *both* the lessac-derivative gray zone **and** an explicitly Unknown
dataset license. **PO decision (#157): KEEP `zh_CN-huayan-medium` as the zh
default.** It is a consistent extension of the accepted lessac-derivative
gray-zone policy — offered download-only (not bundled), low practical risk,
and there is no license-clean from-scratch Piper alternative for zh_CN. No
code change for zh.

**License-clean zh path:** Pro's **Kokoro** engine (Apache-2.0) is the
commercial-safe route for Chinese for Pro users; a future ticket may surface
a Kokoro zh voice as the recommended zh default if a clean Piper voice does
not materialise.

## Removed from the offered catalog (#157)

These voices are no longer listed in the download catalog. Users who already
installed them keep working — the playback path resolves the configured voice
filename directly and does **not** gate on catalog membership — but the app no
longer offers them for download.

| Voice id            | Dataset license          | Reason removed |
|---------------------|--------------------------|----------------|
| `en_US-ryan-high`   | CC BY-NC-SA 4.0 (dataset) | Non-commercial — unacceptable default/offer for a paid app |
| `en_US-ryan-medium` | CC BY-NC-SA 4.0 (dataset) | Non-commercial (same ryan dataset) |
| `en_US-lessac-high` | Blizzard-2013 research-only | Research-only — not commercial-safe |

(`en_US-ryan-medium` was never in PipPal's curated catalog; it is listed here for
completeness because it shares ryan's NC dataset.)

## Clean commercial-safe English alternatives (for reference)

From the #157 memo, confirmed clean English voices: `en_US-ljspeech-high`
(public domain, the new default), `en_US-libritts_r`/`libritts` (CC-BY 4.0),
`cori-high` (public domain).
