"""Real served-UI oracle for searchable Piper multi-speaker selection."""

from __future__ import annotations

import json
import threading

from playwright.sync_api import Page, expect

VOICE = "en_US-libritts-high.onnx"


def _goto_settings(page: Page, app_url: str) -> None:
    page.goto(f"{app_url}/index.html?view=settings")
    expect(page.locator("body")).to_have_attribute("data-ready", "settings", timeout=15_000)


def test_libritts_speaker_picker_searches_limits_and_persists(
    page: Page, app_url: str, backend
) -> None:
    voices_dir = backend["profile"] / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / VOICE).write_bytes(b"model")
    speakers = {str(1000 + index): index for index in range(904)}
    (voices_dir / f"{VOICE}.json").write_text(
        json.dumps({"num_speakers": 904, "speaker_id_map": speakers}),
        encoding="utf-8",
    )
    backend["config"].update({"voice": VOICE, "piper_speaker_ids": {VOICE: 0}})

    _goto_settings(page, app_url)

    row = page.get_by_test_id("settings-piper-speaker-row")
    expect(row).to_be_visible()
    picker = page.get_by_test_id("settings-piper-speaker")
    expect(picker).to_have_value("0")
    assert picker.locator("option").count() <= 50

    search = page.get_by_test_id("settings-piper-speaker-search")
    search.fill("1612")
    expect(picker.locator("option")).to_have_count(1)
    expect(picker.locator("option")).to_have_text("1612")
    picker.select_option("612")
    search.fill("")
    expect(picker.locator("option")).to_have_count(50)
    expect(picker).to_have_value("612")
    page.get_by_test_id("settings-apply").click()
    expect(page.get_by_test_id("toast")).to_contain_text("Applied")

    assert backend["config"]["piper_speaker_ids"] == {VOICE: 612}
    saved = json.loads((backend["profile"] / "config.json").read_text("utf-8"))
    assert saved["piper_speaker_ids"] == {VOICE: 612}


def test_stale_speaker_response_cannot_overwrite_new_voice(
    page: Page,
    app_url: str,
    backend,
) -> None:
    voice_a = "en_US-race-a.onnx"
    voice_b = "en_US-race-b.onnx"
    voices_dir = backend["profile"] / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    for voice, prefix in ((voice_a, "A"), (voice_b, "B")):
        (voices_dir / voice).write_bytes(b"model")
        (voices_dir / f"{voice}.json").write_text(
            json.dumps(
                {
                    "num_speakers": 2,
                    "speaker_id_map": {f"{prefix} zero": 0, f"{prefix} one": 1},
                }
            ),
            encoding="utf-8",
        )
    backend["config"]["voice"] = voice_a
    started = threading.Event()
    release = threading.Event()
    original = backend["bridge"].get_piper_speakers

    def delayed(voice: str, query: str = "", selected_id=None):
        if voice == voice_a:
            started.set()
            release.wait(timeout=5)
        return original(voice, query, selected_id)

    backend["bridge"].get_piper_speakers = delayed
    try:
        _goto_settings(page, app_url)
        assert started.wait(timeout=2)
        page.get_by_test_id("settings-voice").select_option(voice_b)
        picker = page.get_by_test_id("settings-piper-speaker")
        expect(picker.locator("option")).to_have_text(["B zero", "B one"])
        release.set()
        page.wait_for_timeout(250)
        expect(picker.locator("option")).to_have_text(["B zero", "B one"])
    finally:
        release.set()


def test_live_voice_refresh_updates_speaker_picker(
    page: Page,
    app_url: str,
    backend,
) -> None:
    backend["config"]["piper_speaker_ids"] = {VOICE: 999}
    _goto_settings(page, app_url)
    row = page.get_by_test_id("settings-piper-speaker-row")
    expect(row).to_be_hidden()

    voices_dir = backend["profile"] / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    (voices_dir / VOICE).write_bytes(b"model")
    (voices_dir / f"{VOICE}.json").write_text(
        json.dumps(
            {
                "num_speakers": 2,
                "speaker_id_map": {"Speaker 19": 0, "Speaker 26": 1},
            }
        ),
        encoding="utf-8",
    )

    page.evaluate("window.dispatchEvent(new CustomEvent('pippal-installed-voices-changed'))")

    expect(page.get_by_test_id("settings-voice")).to_have_value(VOICE)
    expect(row).to_be_visible()
    picker = page.get_by_test_id("settings-piper-speaker")
    expect(picker.locator("option")).to_have_text(["Speaker 19", "Speaker 26"])
    expect(picker).to_have_value("0")
    page.get_by_test_id("settings-apply").click()
    expect(page.get_by_test_id("toast")).to_contain_text("Applied")
    assert backend["config"]["piper_speaker_ids"] == {VOICE: 0}
