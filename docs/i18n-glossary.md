# PipPal core i18n glossary (T-105 / issue #126)

Translation contract for the five non-English core catalogs
(`webui/i18n/{zh-CN,de,hu,uk,pt-BR}.json`), built **before** translation and
applied consistently. Machine-readable twin: `webui/i18n/_glossary.json`
(underscore-prefixed so the engine's `discover_langs` treats it as a private,
non-catalog file rather than a language tag).
Design reference: `docs/I18N_DESIGN_0_3_1.md` §5.8.

## 1. Product / brand terms — KEEP ENGLISH

| Term | Policy | Note |
|---|---|---|
| **PipPal** | keep | Brand — never translated (also the `window.*` titles that resolve to `"PipPal"`). |
| **Piper** | keep | Local TTS engine name. |
| **Ollama** | keep | Product name (Pro surfaces; listed for cross-repo consistency). |
| **GitHub**, **Reddit** | keep | Brands. The Reddit link localises only the surrounding word (`Community` → `Közösség` / `Спільнота` / `Comunidade`; German keeps the loanword `Community`). |
| **TTS**, **PDF** | keep | Established technical initialisms. |
| **Windows** | keep | OS name (declined/compounded per grammar: `Windows-Integration`, `Інтеграція з Windows`). |

## 2. Translated but glossary-locked terms

Register per language: **de** = *Sie*-form; **uk** = formal (ви); **hu** =
neutral app register with noun/infinitive buttons (`Mentés`, not `Mentsd el`);
**zh-CN** = standard software register; **pt-BR** = *você*-form.

| EN term | de | hu | uk | zh-CN | pt-BR |
|---|---|---|---|---|---|
| voice | Stimme | hang | голос | 语音 | voz |
| engine (TTS) | **Engine** *(DE keeps the loanword)* | motor | рушій | 引擎 | mecanismo |
| hotkey | Tastenkürzel | gyorsbillentyű | гаряча клавіша | 快捷键 | atalho |
| tray | Infobereich | tálca | область сповіщень | 托盘 | bandeja |
| overlay / reader panel | Panel / Lesefenster | panel / olvasópanel | панель / панель читання | 面板 / 朗读面板 | painel / painel de leitura |
| karaoke highlight | Karaoke-Hervorhebung | karaoke-kiemelés | караоке-підсвічування | 卡拉OK高亮 | destaque de karaokê |
| toast | *phrase as a notification/status message; never the literal word* |

## 3. Unit symbols & typography

- `ms`, `px` — kept verbatim in every language (international symbols).
- `KB`/`MB` — Latin except **uk** (Cyrillic `КБ`/`МБ`).
- Typographic characters preserved from en where present: `…  ·  ×  ©  ✓  ⚠  ○`.
- Quotes follow each language: **de** `„…“`, **hu** `„…”`, **uk** `«…»`,
  **zh-CN** `“…”`, **pt-BR** `“…”`.
- Decimal comma in de/hu/uk/pt-BR (`0,6×`); zh-CN keeps the decimal point
  (`0.6×`).

## 4. Whimsical overlay tone (`overlay.loading.*`)

Fourteen loading lines are translated with a **playful** tone (not mechanical),
each kept at roughly ≤ the English length + 20 % for the ~560 px overlay
(German deliberately uses shorter synonyms). Examples: *Warming up the vocal
cords…* → `Stimmbänder aufwärmen…` / `A hangszálak bemelegítése…` /
`Розігріваємо голосові зв'язки…` / `正在热身声带…` / `Aquecendo as cordas vocais…`.

## 5. Plural (CLDR) categories per language

| Lang | Categories | Notes |
|---|---|---|
| zh-CN | other | single form |
| de, hu, pt-BR | one, other | hu: the counted noun is invariant, so `one` and `other` are identical by design |
| uk | one, few, many, other | Slavic 4-form (1→one, 2–4→few, 5–20/0→many, fractions→other) |

Categories are validated against the runtime resolver `pippal.i18n.cldr_plural`
in `tests/test_i18n_catalogs.py`, so the catalog shape can never drift from the
engine that reads it.

## 6. Values that legitimately equal English (test allowlist)

Justified in `tests/test_i18n_catalogs.py`: brand `GitHub`, the `PipPal` window
titles, unit symbols `ms`/`px`, the `voices.row.meta` id-format line, and a few
native-convention words (`de` "Engine"/"Status"/"Community", `pt-BR` "Status").
Anything else equalling English fails the suite as an untranslated gap.

## 7. Native-review sign-off checklist (human gate — recorded in the PR)

Per language, a native reviewer confirms: (a) register/formality correct;
(b) glossary terms applied consistently; (c) whimsical lines read playfully and
fit the overlay width; (d) plural forms natural; (e) placeholders intact and
sentences grammatical around them.
