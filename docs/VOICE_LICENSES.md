# Voice licenses (Piper TTS)

This document records the dataset license and model lineage of every voice
PipPal ships as a **language default**, plus the rationale for voices that were
deliberately **removed** from the offered catalog. It is the licensing source of
truth referenced by issue #157.

Sources: the per-voice `MODEL_CARD` files under
`huggingface.co/rhasspy/piper-voices`, the original dataset publications, and
the dataset owners' terms (re-verified 2026-07-16).

## Why this matters

PipPal is a paid application. Without written permission, a default voice whose
**dataset** carries a non-commercial (NC) or research-only license is not an
acceptable out-of-the-box default. The EN default was therefore moved off
`en_US-ryan-high` onto `en_US-ljspeech-high` (public domain).

## Per-default-voice license table

| UI lang | Default voice id       | Dataset | Dataset license | Model lineage | Verdict |
|---------|------------------------|---------|-----------------|---------------|---------|
| en      | `en_US-ljspeech-high`  | LJ Speech | **Public domain** | Trained from scratch | Lower-risk — no known NC restriction |
| de      | `de_DE-thorsten-high`  | Thorsten-Voice | **CC0** | Finetuned from U.S. English lessac | CC0 data; see lessac-lineage note |
| hu      | `hu_HU-anna-medium`    | OHF-Voice voice-datasets | **CC0** | Finetuned from U.S. English lessac | GRAY (lessac-derived) — PO-accepted |
| uk      | `uk_UA-ukrainian_tts-medium` | OHF-Voice voice-datasets | **CC0** | Trained from scratch | Lower-risk — no known NC restriction |
| pt-BR   | `pt_BR-faber-medium`   | OHF-Voice voice-datasets | **CC0** | Finetuned from U.S. English lessac | GRAY (lessac-derived) — PO-accepted |
| zh-CN   | `zh_CN-huayan-medium`  | HuaYan_TTS | **Unknown** | Finetuned from U.S. English lessac | GRAY (Unknown license + lessac-derived) — PO-accepted as download-only default; see note |

### lessac-derivative gray-zone note (hu, pt-BR, de, zh)

Several Piper voices are *model-finetuned* from the U.S. English **lessac** voice
(whose training corpus, Blizzard-2013, is research-only). The finetune datasets
for hu/pt-BR/de are CC0, but the resulting model weights carry a lineage from
lessac. These defaults are documented as lower-risk choices with no known NC
restriction in their finetune datasets, not as legally cleared weights: the
derivative-weights question remains unsettled. The separate zh section below
covers its Unknown dataset license and Lessac lineage.

### zh-CN huayan — verification finding + PO decision (#157)

`zh_CN-huayan-medium` was verified against its HF `MODEL_CARD`:

- Dataset: <https://github.com/PlayVoice/HuaYan_TTS>
- **Dataset license: Unknown**
- Model lineage: **finetuned from the U.S. English lessac voice** (medium).

This is *both* the lessac-derivative gray zone **and** an explicitly Unknown
dataset license. **PO decision (#157): KEEP `zh_CN-huayan-medium` as the zh
default.** It is a consistent extension of the accepted lessac-derivative
gray-zone policy — offered download-only (not bundled), low practical risk,
and there is no known lower-risk from-scratch Piper alternative for zh_CN. No
code change for zh.

**Lower-risk zh path:** Pro's **Kokoro** distribution is Apache-2.0 and is the
currently preferred route for Chinese for Pro users, subject to retaining its
required notices. A future ticket may surface a Kokoro zh voice as the
recommended default if a lower-risk Piper voice does not materialise.

## Removed from the offered catalog (#157)

These voices are no longer listed in the download catalog. Users who already
installed them keep working — the playback path resolves the configured voice
filename directly and does **not** gate on catalog membership — but the app no
longer offers them for download.

| Voice id            | Published terms          | Reason removed |
|---------------------|--------------------------|----------------|
| `en_US-ryan-high`   | Conflicting: Piper card says CC BY-NC-SA 4.0; official RyanSpeech terms say CC BY-NC-ND 4.0 | Named download disabled pending written permission and provenance clarification |
| `en_US-ryan-medium` | Same RyanSpeech conflict | Named download disabled pending written permission and provenance clarification |
| `en_US-ryan-low`    | Same RyanSpeech conflict | Named download disabled pending written permission and provenance clarification |
| `en_US-lessac-high` | Blizzard-2013 research-only | Research-only — not commercial-safe |

All three Ryan qualities were previously present across the Core and Pro
catalogs. The official RyanSpeech request page limits the database to
non-commercial research/education and says it may not be transferred to third
parties, while the Piper model card reports a different Creative Commons
license. The Piper maintainer does not provide a legal conclusion for generated
model weights. Until the RyanSpeech owner confirms the ONNX distribution and
commercial product integration in writing, PipPal does not present a named
one-click Ryan install action.

This does **not** disable generic Piper/ONNX compatibility. Existing or
user-supplied models continue to work, and PipPal does not host the Ryan model
weights. Generic compatibility and a curated named download are deliberately
treated as different product decisions.

Primary references:

- Piper Ryan model card: <https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ryan/high/MODEL_CARD>
- Official RyanSpeech terms/contact: <https://www.mohammadmahoor.com/pages/databases/ryanspeech/forms/ryanspeech/>
- RyanSpeech paper: <https://www.isca-archive.org/interspeech_2021/zandie21_interspeech.html>
- Piper maintainer discussion: <https://github.com/rhasspy/piper/discussions/271>

## Lower-risk English alternatives (for reference)

Lower-risk English choices include `en_US-ljspeech-high` (public domain, the
new default), plain `en_US-libritts-high` (trained from scratch on CC BY 4.0
LibriTTS; 904 selectable speakers), and `en_GB-cori-high` (public-domain
LibriVox data). CC BY 4.0 requires attribution; PipPal must retain the LibriTTS
credit when it presents or redistributes the model.

Do not conflate plain `libritts` with `libritts_r`: Piper's
`en_US-libritts_r-medium` model was fine-tuned from Lessac and therefore keeps
the Lessac-lineage gray zone described above. It is not listed as a lower-risk
equivalent to the from-scratch LibriTTS model.

References:

- Plain LibriTTS model card: <https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/libritts/high/MODEL_CARD>
- LibriTTS dataset/license: <https://www.openslr.org/60/>
- LibriTTS-R model card: <https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/libritts_r/medium/MODEL_CARD>
