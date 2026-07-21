# Third-Party Notices

PipPal itself is MIT-licensed (see [LICENSE.md](../LICENSE.md)). It depends on a
small number of third-party packages and, at run-time, expects the user
to download two upstream artefacts (the Piper engine and a voice). This
file lists what is involved and under what terms.

## Python dependencies (installed via pip)

| Package | License | Notes |
|---|---|---|
| [keyboard](https://github.com/boppreh/keyboard) | MIT | Global hotkey dispatch. |
| [pyperclip](https://github.com/asweigart/pyperclip) | BSD-3-Clause | Clipboard get/set. |
| [pystray](https://github.com/moses-palmer/pystray) | LGPL-3.0 | Tray icon. Used as an unmodified, dynamically-linked library — no LGPL obligation propagates to PipPal. |
| [Pillow](https://python-pillow.org/) | MIT-CMU (HPND) | Image generation for the tray icon. |
| [pytest](https://pytest.org/), [ruff](https://docs.astral.sh/ruff/), [mypy](https://mypy-lang.org/) | MIT | Dev-only. |

The dependency tree is small and entirely permissive. None of these
licences require PipPal itself to adopt a copyleft licence.

## Run-time artefacts (downloaded by `setup.ps1`)

These are **not** distributed with the PipPal source repository. The
setup script fetches them from the upstream projects' release pages
when the user runs it for the first time.

### Piper

- Project: <https://github.com/rhasspy/piper>
- Licence: **MIT**
- Bundled by upstream Piper: **eSpeak NG (GPL-3.0)** as
  `espeak-ng.dll`. PipPal calls `piper.exe` as a subprocess and never
  loads `espeak-ng.dll` into its own process, so the GPL boundary
  stays inside Piper's executable. PipPal does not redistribute either
  binary — `setup.ps1` downloads the official Piper release.

### Piper voices

- Catalogue: <https://huggingface.co/rhasspy/piper-voices>
- Licences: **per voice** — see each voice's model card. PipPal does not ship
  voice files; the user downloads them on demand.

#### Plain LibriTTS voice attribution

PipPal offers the from-scratch `en_US-libritts-high` Piper model as an optional
download. It uses the **LibriTTS** dataset, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Dataset/source:
[OpenSLR 60 — LibriTTS](https://www.openslr.org/60/). Piper model card:
[`en_US-libritts-high`](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/libritts/high/MODEL_CARD).
Dataset authors: **Heiga Zen et al.**
This notice supplies the required attribution; downstream redistributors must
retain it.

`en_US-libritts_r-medium` is a different model. Its Piper model card records
fine-tuning from the Lessac medium voice, so it retains the Lessac-lineage gray
zone and is not treated as equivalent to the from-scratch LibriTTS model:
[`en_US-libritts_r-medium`](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/libritts_r/medium/MODEL_CARD).

### ONNX Runtime (bundled inside the Piper release)

- Project: <https://github.com/microsoft/onnxruntime>
- Licence: **MIT**.

## Trademarks

"Piper", "ONNX", "Hugging Face", "Windows", "Microsoft" and other
product names are trademarks of their respective owners. Use of these
names in PipPal is purely descriptive.
