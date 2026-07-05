"""T-304 system-language fallback MATRIX — the full Auto ("") resolve path.

The T-107 unit tests (``tests/test_i18n_engine.py``) already assert
``detect_system_language`` / ``resolve_language`` against a hand-passed
supported list. This file extends that pattern end-to-end: it drives the
REAL runtime resolve path a fresh "Auto" profile takes — ``config.language
== ""`` -> :func:`pippal.i18n.set_language` -> :func:`resolve_language` ->
:func:`detect_system_language` -> the monkeypatched OS locale seam
(``_read_system_locale``, the single ``GetUserDefaultLocaleName`` boundary)
— using the ACTUAL discovered ``SUPPORTED_LANGS`` (the shipped catalog set,
never a literal list), and then proves the loop closes: the ACTIVE language
becomes the resolved tag AND ``t()`` renders a real catalog key in that
language.

Matrix (issue #339 system-fallback AC), each seeded via a mocked OS locale
with ``config.language == ""`` (Auto):

  * ``de-AT`` -> ``de``   (Austrian German -> the bare shipped German tag)
  * ``zh-TW`` -> ``zh-CN`` (Traditional-region Chinese -> the shipped zh-CN)
  * ``pt-PT`` -> ``pt-BR`` (European Portuguese -> the only shipped pt variant)
  * ``fi``    -> ``en``    (unsupported -> English fallback)

Oracle-first: the resolved tag is checked against the design precedence rules
and the expected rendered string is read FROM the shipped catalog, so a
regression in the mapping, the active-language global, or the catalog load
all fail here.
"""

from __future__ import annotations

import pytest

from pippal import i18n

# The four issue-named locale -> resolved-language vectors, plus the two
# boundary anchors the AC implies (an exact regional match that keeps its
# bare tag, and the empty/no-locale -> en degrade).
FALLBACK_MATRIX = [
    ("de-AT", "de"),
    ("zh-TW", "zh-CN"),
    ("pt-PT", "pt-BR"),
    ("fi", "en"),
    ("en-GB", "en"),
    ("uk-UA", "uk"),
    ("", "en"),
]

# A real catalog key present (and translated) in every shipped language — the
# rendered-output oracle that proves detection -> active language -> t() agree.
_RENDER_KEY = "chrome.close"


@pytest.fixture
def restore_active_language():
    """Save/restore the module-level active language so this suite's
    ``set_language`` calls never leak into another test's ``t()`` output."""
    original = i18n.get_language()
    yield
    i18n.set_language(original)


@pytest.mark.parametrize(("system_locale", "expected"), FALLBACK_MATRIX)
def test_auto_config_resolves_system_locale_through_real_path(
    monkeypatch: pytest.MonkeyPatch,
    restore_active_language,
    system_locale: str,
    expected: str,
) -> None:
    # Mock ONLY the OS boundary; everything above it is the real runtime.
    monkeypatch.setattr(i18n, "_read_system_locale", lambda: system_locale)

    # The resolved language uses the ACTUAL shipped catalog set, not a literal.
    supported = i18n.discover_langs()
    assert expected in supported, f"{expected!r} not a shipped catalog"

    # config.language == "" (Auto) -> the exact resolver save_config invokes.
    resolved = i18n.resolve_language("", supported)
    assert resolved == expected, (
        f"OS locale {system_locale!r} (Auto) should resolve {expected!r}, "
        f"got {resolved!r}"
    )

    # Drive the full active-language runtime path (what save_config triggers)
    # and confirm the on-demand Python surface language follows.
    active = i18n.set_language("", supported)
    assert active == expected == i18n.get_language(), (
        f"active language after Auto resolve should be {expected!r}"
    )

    # Close the loop: t() renders the resolved language's catalog value (an
    # independent oracle read straight from that language's shipped catalog).
    catalog_value = i18n.load_catalog(expected).get(_RENDER_KEY)
    assert isinstance(catalog_value, str), f"{_RENDER_KEY} absent from {expected}"
    assert i18n.t(_RENDER_KEY) == catalog_value, (
        f"t({_RENDER_KEY!r}) did not render the resolved {expected!r} value"
    )


def test_explicit_pick_overrides_system_locale(
    monkeypatch: pytest.MonkeyPatch, restore_active_language
) -> None:
    """An explicit ``config.language`` beats the OS locale (precedence rule):
    a Ukrainian pick wins even though the mocked system says Austrian German."""
    monkeypatch.setattr(i18n, "_read_system_locale", lambda: "de-AT")
    supported = i18n.discover_langs()

    assert i18n.resolve_language("uk", supported) == "uk"
    assert i18n.set_language("uk", supported) == "uk"
    uk_close = i18n.load_catalog("uk").get(_RENDER_KEY)
    assert isinstance(uk_close, str)
    assert i18n.t(_RENDER_KEY) == uk_close


def test_unsupported_explicit_pick_falls_through_to_system(
    monkeypatch: pytest.MonkeyPatch, restore_active_language
) -> None:
    """An unsupported explicit pick is ignored and resolution falls through
    to the (mocked) system locale — de-AT -> de — never crashing."""
    monkeypatch.setattr(i18n, "_read_system_locale", lambda: "de-AT")
    supported = i18n.discover_langs()
    assert i18n.resolve_language("zz-ZZ", supported) == "de"
