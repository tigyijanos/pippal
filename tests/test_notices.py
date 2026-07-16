from pippal import notices


def test_bundled_notice_attributes_plain_libritts() -> None:
    notice_path = notices.resolve_notices_path()

    assert notice_path is not None
    text = notice_path.read_text(encoding="utf-8")
    assert "en_US-libritts-high" in text
    assert "Heiga Zen et al." in text
    assert "CC BY 4.0" in text
    assert "https://www.openslr.org/60/" in text
    assert "en_US-libritts_r-medium" in text


def test_resolve_notices_prefers_packaged_notices_file(tmp_path):
    notices_file = tmp_path / "NOTICES.txt"
    notices_file.write_text("bundled notices", encoding="utf-8")

    assert notices.resolve_notices_path([tmp_path]) == notices_file


def test_resolve_notices_falls_back_to_source_third_party_doc(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    third_party = docs / "THIRD_PARTY.md"
    third_party.write_text("source notices", encoding="utf-8")

    assert notices.resolve_notices_path([tmp_path]) == third_party


def test_resolve_notices_returns_none_when_missing(tmp_path):
    assert notices.resolve_notices_path([tmp_path]) is None
