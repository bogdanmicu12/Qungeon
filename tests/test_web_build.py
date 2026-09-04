"""Integrity checks for the minimal static browser entry point."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def test_every_configured_browser_file_exists():
    config = json.loads((WEB / "pyscript.json").read_text(encoding="utf-8"))

    assert config["packages"] == ["cirq-core==1.7.0"]
    missing = [url for url in config["files"] if not (WEB / url).is_file()]
    assert missing == []


def test_browser_uses_original_game_files_without_copies():
    config = json.loads((WEB / "pyscript.json").read_text(encoding="utf-8"))

    assert config["files"]["../Qungeon.py"] == "./Qungeon.py"
    assert not (WEB / "Qungeon.py").exists()
    assert not (WEB / "assets").exists()
    assert not (WEB / "levels").exists()
    assert not (WEB / "scripts").exists()


def test_bundled_unitary_alpha_matches_pinned_checkout_when_available():
    source = ROOT / "src" / "unitary" / "unitary" / "alpha"
    if not source.is_dir():
        return

    modules = list((WEB / "unitary" / "alpha").glob("*.py"))
    assert all(
        digest(source / module.name) == digest(module)
        for module in modules
    )
