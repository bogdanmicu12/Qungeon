"""Integrity checks for the minimal static browser entry point."""

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def test_menu_and_editor_start_without_the_quantum_stack():
    """Reproduce browser boot before micropip has installed gameplay packages.

    Use a fresh interpreter so another test cannot mask an eager import by
    leaving the quantum modules cached in sys.modules.
    """
    result = subprocess.run(
        [sys.executable, "-c", """
import importlib.abc
import os
import sys
from types import SimpleNamespace

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

class BlockQuantumImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"cirq", "unitary", "numpy", "scipy"}:
            raise ModuleNotFoundError(f"Premature quantum import: {fullname}")

sys.meta_path.insert(0, BlockQuantumImports())

import pygame
from Qungeon import Game

game = Game(SimpleNamespace(level=1), settings={},
            persist_settings=lambda _: True, gameplay_downloaded=lambda: False)
assert game.menu.page == "main"
game.run_frame()
game.open_editor()
assert game.menu.page == "editor"
game.run_frame()
assert game.quantum_grid is None
assert game.hotbar is None
pygame.quit()
"""],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_configured_browser_file_exists():
    config = json.loads((WEB / "pyscript.json").read_text(encoding="utf-8"))

    missing = [url for url in config["files"] if not (WEB / url).is_file()]
    assert missing == []


def test_the_quantum_stack_is_not_installed_during_boot():
    """cirq and its dependencies are ~37 MB and nothing on the menu needs them.

    Listing them here installs them before any Python runs, which held the
    loading screen up for ~20s. web/main.py installs them with micropip once
    the menu is on screen instead.
    """
    config = json.loads((WEB / "pyscript.json").read_text(encoding="utf-8"))

    assert config["packages"] == ["micropip"]
    assert "cirq-core==1.7.0" in (WEB / "main.py").read_text(encoding="utf-8")


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


def module_level_imports(path):
    """`scripts.*` modules a file imports at load time (not inside functions)."""
    found, todo = set(), list(ast.parse(path.read_text(encoding="utf-8")).body)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
            if node.module == "scripts":
                names += [f"scripts.{alias.name}" for alias in node.names]
            found.update(name for name in names if name.startswith("scripts."))
        todo.extend(ast.iter_child_nodes(node))
    return found


def test_browser_ships_everything_the_game_loads():
    """A module, level or unitary file missing here only fails in the browser."""
    config = json.loads((WEB / "pyscript.json").read_text(encoding="utf-8"))
    shipped = {target.removeprefix("./") for target in config["files"].values()}

    needed, todo = set(), [ROOT / "Qungeon.py"]
    while todo:
        for module in module_level_imports(todo.pop()):
            relative = module.replace(".", "/") + ".py"
            if relative not in needed and (ROOT / relative).is_file():
                needed.add(relative)
                todo.append(ROOT / relative)

    needed |= {f"levels/{path.name}" for path in (ROOT / "levels").glob("*.json")}
    needed |= {
        f"unitary/alpha/{path.name}"
        for path in (WEB / "unitary" / "alpha").glob("*.py")
    }
    needed |= {
        f"assets/{path.name}"
        for path in (ROOT / "assets").glob("*-gate.png")
    }

    assert sorted(needed - shipped) == []
