import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.3.3"


def test_release_version_surfaces_are_synchronized() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_init = (ROOT / "src/pippal/__init__.py").read_text(encoding="utf-8")
    installer = (ROOT / "packaging/installer/pippal.iss").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == VERSION
    assert f'__version__ = "{VERSION}"' in package_init
    assert f'#define MyAppVersion   "{VERSION}"' in installer
    assert "AppId={{B7E3F2A1-4C9D-4E6B-8F0A-1D2E3C4B5A67}" in installer
    assert f"Core v{VERSION}" in readme
    assert changelog.index(f"## {VERSION}") < changelog.index("## 0.3.2")


def test_release_workflow_targets_current_installer_and_tag() -> None:
    workflow = (ROOT / ".github/workflows/release-installer.yml").read_text(encoding="utf-8")

    assert "PipPal-Setup-0.3.3.exe" in workflow
    assert "name: PipPal-Setup-0.3.3" in workflow
    assert '$tag       = "v0.3.3"' in workflow
    assert "PipPal-Setup-0.3.2" not in workflow
    assert "v0.3.2" not in workflow
