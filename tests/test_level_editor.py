"""The editor must consult the solver before it permits a test run."""

from types import SimpleNamespace

from scripts.level_editor import LevelEditor


class CompletedTask:
    """Small stand-in for a completed frame-sliced solver task."""

    def __init__(self, solvable):
        self.solution = SimpleNamespace(solvable=solvable)

    def advance(self, _node_limit):
        return self.solution


def editor_for(tmp_path, monkeypatch, solvable):
    """Build just enough editor state to exercise its save boundary."""
    monkeypatch.chdir(tmp_path)
    statuses = []
    starts = []
    game = SimpleNamespace(
        start_level_solver_task=lambda data: CompletedTask(solvable),
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
    editor.checking_action = None
    editor._pending_save = None
    editor._solver_task = None
    editor._check_rendered = False
    return editor, statuses, starts


def wait_for_check(editor):
    """Advance the editor's frame-sliced solver until it completes."""
    for _ in range(100):
        editor.update()
        if editor.checking_action is None:
            return
    raise AssertionError("level check did not finish")


def test_unsolvable_level_is_saved_but_cannot_be_tested(tmp_path, monkeypatch):
    editor, statuses, starts = editor_for(tmp_path, monkeypatch, False)

    assert editor.save() is False
    wait_for_check(editor)
    assert (tmp_path / "levels" / "12.json").exists()
    assert "Not solvable yet" in statuses[-1]

    editor.activate("TEST")
    wait_for_check(editor)

    assert starts == []


def test_solvable_level_can_be_tested(tmp_path, monkeypatch):
    editor, statuses, starts = editor_for(tmp_path, monkeypatch, True)

    editor.activate("TEST")
    wait_for_check(editor)

    assert starts == [(12, "single")]
    assert statuses[-1] == "Saved level 12 (solvable)"


def test_save_reports_checking_and_does_not_commit_before_the_result(
    tmp_path,
    monkeypatch,
):
    started = []
    released = []
    editor, statuses, _ = editor_for(tmp_path, monkeypatch, True)

    class PendingTask:
        def advance(self, _node_limit):
            return SimpleNamespace(solvable=True) if released else None

    def start_task(_data):
        started.append(True)
        return PendingTask()

    editor.game.start_level_solver_task = start_task

    assert editor.save() is False
    assert editor.checking_action == "SAVE"
    assert statuses[-1] == "Checking level validity..."
    assert not (tmp_path / "levels" / "12.json").exists()

    editor.update()
    assert started
    assert not (tmp_path / "levels" / "12.json").exists()

    released.append(True)
    wait_for_check(editor)

    assert (tmp_path / "levels" / "12.json").exists()
