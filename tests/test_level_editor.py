"""The editor must consult the solver before it permits a test run."""

from types import SimpleNamespace

from scripts.level_editor import LevelEditor


def editor_for(tmp_path, monkeypatch, solvable):
    """Build just enough editor state to exercise its save boundary."""
    monkeypatch.chdir(tmp_path)
    statuses = []
    starts = []
    game = SimpleNamespace(
        solve_level_data=lambda data: SimpleNamespace(solvable=solvable),
        find_levels=lambda: [12],
        available_levels=[],
        menu=SimpleNamespace(previews={12: object()}),
        start_level=lambda level, mode: starts.append((level, mode)),
    )
    editor = object.__new__(LevelEditor)
    editor.game = game
    editor.level_number = lambda: 12
    editor.data = lambda: {
        "tiles": {"(0, 0)": "START", "(1, 0)": "END"},
        "objects": {},
        "quantum_objects": [],
        "gates": {},
        "effects": [],
    }
    editor.set_status = statuses.append
    return editor, statuses, starts


def test_unsolvable_level_is_saved_but_cannot_be_tested(tmp_path, monkeypatch):
    editor, statuses, starts = editor_for(tmp_path, monkeypatch, False)

    assert editor.save() is False
    assert (tmp_path / "levels" / "12.json").exists()
    assert "Not solvable yet" in statuses[-1]

    editor.activate("TEST")

    assert starts == []


def test_solvable_level_can_be_tested(tmp_path, monkeypatch):
    editor, statuses, starts = editor_for(tmp_path, monkeypatch, True)

    editor.activate("TEST")

    assert starts == [(12, "single")]
    assert statuses[-1] == "Saved level 12 (solvable)"
