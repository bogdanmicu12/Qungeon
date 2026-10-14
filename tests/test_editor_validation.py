"""Editor checks must show progress, keep input alive, and act only on checked data."""

import copy
import json
import os
import time
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from Qungeon import Game
from scripts import level_editor
from scripts.level_check import check_level
from scripts.level_check_job import LevelCheckJob


def level(one=False, gates=None):
    return {
        "editor_created": True,
        "tiles": {"(1, 1)": "START", "(2, 1)": "EMPTY", "(3, 1)": "END"},
        "objects": {}, "quantum_objects": ["(2, 1)"],
        "pillar_states": {"(2, 1)": {"x": 0 if one else 1, "y": 1 if one else 0}},
        "gates": gates or {}, "effects": [],
    }


@pytest.fixture
def editor(monkeypatch):
    game = Game(SimpleNamespace(level=1), settings={}, persist_settings=lambda _: True,
                gameplay_downloaded=lambda: False)
    game.open_editor()
    editor = game.editor
    # Use structurally valid data; these tests isolate asynchronous UI behavior.
    data = level()
    monkeypatch.setattr(editor, "data", lambda: copy.deepcopy(data))
    editor.level_text = "999"
    return editor, data


@pytest.fixture
def jobs(monkeypatch):
    created = []

    class ControlledJob:
        @staticmethod
        def prepare():
            pass

        def __init__(self, data):
            self.data = copy.deepcopy(data)
            self.result = None
            self.cancelled = False
            created.append(self)

        def poll(self):
            return self.result

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(level_editor, "LevelCheckJob", ControlledJob)
    return created


def launch(editor, jobs, action):
    editor.activate(action)
    assert editor.status == "Checking level validity"
    editor.update_validation()
    assert jobs == []  # Solver cannot start before the progress button is drawn.
    editor.draw()
    editor.update_validation()
    assert len(jobs) == 1


def test_main_menu_spacing_and_footer_clearance(editor):
    menu = editor[0].game.menu
    menu.open("main")
    buttons = menu.buttons()
    left = [rect for _, rect, _, _ in buttons if rect.left == 60]
    assert len({following.top - previous.bottom for previous, following in zip(left, left[1:])}) == 1
    assert all(rect.bottom <= 540 for _, rect, _, _ in buttons)
    assert not any(a.colliderect(b) for i, (_, a, _, _) in enumerate(buttons)
                   for _, b, _, _ in buttons[i + 1:])


def test_editor_controls_remain_accessible(editor):
    actions = {action for action, _, _ in editor[0].buttons()}
    assert {"STATE_ZERO", "STATE_ONE", "STATE_APPLY", "STATE_CLEAR", "SAVE", "TEST",
            "COPY_SHARE", "SAVE_EXIT", "BACK"} <= actions


def test_click_one_then_set_state_applies_to_the_actual_level(editor, monkeypatch):
    editor, _ = editor
    monkeypatch.setattr(editor, "data", lambda: level_editor.LevelEditor.data(editor))
    editor.set_tile((1, 1), "START")
    editor.set_tile((2, 1), "EMPTY")
    editor.set_tile((3, 1), "END")
    editor.add_pillar((2, 1))
    editor.draw()
    original = editor.pillar_preview((2, 1))[0]
    one = next(rect for action, rect, _ in editor.buttons() if action == "STATE_ONE")
    editor.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=one.center))
    assert (editor.state_x_text, editor.state_y_text) == ("0", "1")
    assert editor.pillar_preview((2, 1))[0] is original  # Applied only on Set state.
    apply = next(rect for action, rect, _ in editor.buttons() if action == "STATE_APPLY")
    editor.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=apply.center))
    assert editor.pillar_preview((2, 1))[1:] == (0, 1)
    assert editor.pillar_preview((2, 1))[0] is not original
    data = editor.data()
    assert data["pillar_states"]["(2, 1)"] == {
        "x": {"real": 0.0, "imag": 0.0}, "y": {"real": 1.0, "imag": 0.0},
    }
    assert check_level(data)["solvable"] is False
    editor.gates["X"] = 1
    assert check_level(editor.data())["solvable"] is True
    editor.activate("STATE_ZERO")
    editor.activate("STATE_APPLY")
    assert editor.pillar_preview((2, 1))[1:] == (1, 0)


def test_typing_replaces_focused_amplitude_and_ctrl_a_selects_again(editor):
    editor, _ = editor
    editor.add_pillar((2, 1))
    editor.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(540, 380)))
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_0, unicode="0", mod=0))
    assert editor.state_x_text == "0"  # Must replace the initial 1, not append to it.
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, unicode="", mod=pygame.KMOD_CTRL))
    editor.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1, unicode="1", mod=0))
    assert editor.state_x_text == "1"


@pytest.mark.parametrize("action", ["STATE_APPLY", "STATE_CLEAR"])
def test_state_buttons_flash_when_clicked_then_return_to_normal(editor, monkeypatch, action):
    editor, _ = editor
    editor.add_pillar((2, 1))
    clock = [1000]
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: clock[0])
    button = next(rect for name, rect, _ in editor.buttons() if name == action)
    sample = (button.x + 3, button.y + 3)
    editor.draw()
    assert tuple(editor.game.screen.get_at(sample))[:3] == level_editor.PANEL
    editor.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.center))
    editor.draw()
    assert tuple(editor.game.screen.get_at(sample))[:3] == level_editor.MINT
    clock[0] += 301
    editor.draw()
    assert tuple(editor.game.screen.get_at(sample))[:3] == level_editor.PANEL


def test_set_state_changes_rendered_pillar_immediately(editor):
    editor, _ = editor
    editor.add_pillar((2, 1))
    editor.draw()
    rect = pygame.Rect(level_editor.GRID_X + 2 * level_editor.CELL,
                       level_editor.GRID_Y + level_editor.CELL,
                       level_editor.CELL, level_editor.CELL)

    def rendered():
        return pygame.image.tobytes(editor.game.screen.subsurface(rect), "RGBA")

    zero = rendered()
    editor.state_x_text, editor.state_y_text = "0", "1"
    button = next(rect for action, rect, _ in editor.buttons() if action == "STATE_APPLY")
    editor.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.center))
    editor.draw()
    one = rendered()
    assert one != zero
    assert editor.pillar_preview((2, 1))[1:] == (0.0, 1.0)

    editor.state_x_text, editor.state_y_text = "1", "1"
    editor.activate("STATE_APPLY")
    editor.draw()
    assert rendered() not in (zero, one)
    assert editor.pillar_preview((2, 1))[1:] == pytest.approx((0.5, 0.5))

    editor.activate("STATE_CLEAR")
    editor.draw()
    assert rendered() == zero


def test_invalid_amplitudes_keep_previous_pillar_color(editor):
    editor, _ = editor
    editor.add_pillar((2, 1))
    original = editor.pillar_preview((2, 1))[0]
    editor.state_x_text, editor.state_y_text = "0", "0"
    editor.activate("STATE_APPLY")
    assert editor.pillar_preview((2, 1))[0] is original
    assert "non-zero" in editor.status


def test_editor_draw_prepares_checker_once_without_starting_a_search(editor, jobs, monkeypatch):
    editor, _ = editor
    calls = []
    monkeypatch.setattr(level_editor.LevelCheckJob, "prepare", lambda: calls.append("prepare"))
    editor.draw()
    editor.draw()
    assert calls == ["prepare"] and jobs == []


def test_new_level_prepares_again_after_cancelling_a_check(editor, jobs, monkeypatch):
    editor, _ = editor
    calls = []
    monkeypatch.setattr(level_editor.LevelCheckJob, "prepare", lambda: calls.append("prepare"))
    launch(editor, jobs, "SAVE_EXIT")
    editor.activate("NEW")
    editor.draw()
    assert jobs[0].cancelled and calls == ["prepare", "prepare"]


def test_validation_distinguishes_worker_preparation_from_search(editor, jobs):
    editor, _ = editor
    launch(editor, jobs, "SAVE_EXIT")
    jobs[0].phase = "preparing"
    editor.update_validation()
    assert "Preparing level checker" in editor.status
    jobs[0].phase = "checking"
    editor.update_validation()
    assert "searching for a solution" in editor.status


def test_save_exit_shows_progress_and_keeps_input_alive(editor, jobs, monkeypatch):
    editor, data = editor
    saved = []
    monkeypatch.setattr(editor, "save_validated", lambda n, data: saved.append((n, data)) or True)
    launch(editor, jobs, "SAVE_EXIT")
    editor.activate("SAVE_EXIT")
    editor.activate("COPY_SHARE")
    editor.activate("WALL")
    editor.game.run_frame()
    assert editor.tool == "WALL"
    assert len(jobs) == 1 and saved == []
    jobs[0].result = {"solvable": True, "message": "Level is valid"}
    editor.update_validation()
    assert saved == [(999, data)]
    assert editor.game.menu.page == "main"


@pytest.mark.parametrize("answer", [False, None])
@pytest.mark.parametrize("action", ["SAVE_EXIT", "COPY_SHARE"])
def test_rejected_or_unknown_level_stays_in_editor(editor, jobs, monkeypatch, answer, action):
    editor, _ = editor
    monkeypatch.setattr(editor, "save_validated", lambda *_: pytest.fail("unchecked save"))
    monkeypatch.setattr(editor, "copy_validated_share", lambda *_: pytest.fail("unchecked copy"))
    launch(editor, jobs, action)
    jobs[0].result = {"solvable": answer, "message": "Cannot confirm this level"}
    editor.update_validation()
    assert editor.game.menu.page == "editor"
    assert editor.validation is None
    assert editor.status == "Cannot confirm this level"


def test_copy_always_checks_current_data_even_with_cached_share_code(editor, jobs, monkeypatch):
    editor, data = editor
    copied = []
    editor.share_code = "QGL-OLD"
    monkeypatch.setattr(editor, "copy_validated_share", copied.append)
    launch(editor, jobs, "COPY_SHARE")
    assert copied == [] and jobs[0].data == data
    jobs[0].result = {"solvable": True, "message": "Level is valid"}
    editor.update_validation()
    from scripts.level_share import decode_level
    from scripts.level_share import encode_level
    assert copied[0] == encode_level(data)
    assert decode_level(copied[0])["tiles"] == data["tiles"]


def test_edits_during_check_prevent_saving_stale_snapshot(editor, jobs, monkeypatch):
    editor, data = editor
    monkeypatch.setattr(editor, "save_validated", lambda *_: pytest.fail("stale save"))
    launch(editor, jobs, "SAVE_EXIT")
    data["gates"]["X"] = 1
    assert jobs[0].data["gates"] == {}
    jobs[0].result = {"solvable": True, "message": "Level is valid"}
    editor.update_validation()
    assert editor.game.menu.page == "editor"
    assert "changed" in editor.status.lower()


def test_back_cancels_pending_check(editor, jobs):
    editor, _ = editor
    launch(editor, jobs, "SAVE_EXIT")
    editor.activate("BACK")
    assert jobs[0].cancelled and editor.validation is None
    assert editor.game.menu.page == "main"


def test_checked_save_writes_snapshot_and_updates_available_levels(editor, jobs, tmp_path, monkeypatch):
    editor, data = editor
    launch(editor, jobs, "SAVE_EXIT")
    monkeypatch.chdir(tmp_path)
    jobs[0].result = {"solvable": True, "message": "Level is valid"}
    editor.update_validation()
    assert json.loads((tmp_path / "levels/999.json").read_text()) == data
    assert editor.game.available_levels == [999]
    assert editor.game.menu.page == "main"


@pytest.mark.parametrize("data, expected", [(level(), True), (level(True), False),
                                           (level(True, {"X": 1}), True)])
def test_checker_uses_actual_pillar_amplitudes(data, expected):
    assert check_level(data)["solvable"] is expected


def test_exhausted_search_is_not_approved():
    assert check_level(level(True, {"X": 1}), budget=0)["solvable"] is None


def test_editor_amplitudes_match_loaded_game(editor):
    import numpy as np
    from scripts.level_solver import state_from_level_data, snapshot

    editor, _ = editor
    data = level()
    data["pillar_states"]["(2, 1)"] = {
        "x": {"real": 0.5, "imag": 0.5},
        "y": {"real": 0.5, "imag": -0.5},
    }
    editor.game.load_level_data(data)
    simulated = snapshot(editor.game).blocks[0].vector
    checked = state_from_level_data(data).blocks[0].vector
    assert np.allclose(simulated, checked)


def test_editor_checks_agree_with_in_game_checks_for_shipped_and_custom_levels(editor):
    from pathlib import Path
    from scripts.level_solver import solve_level_data, solve, snapshot

    editor, _ = editor
    cases = [json.loads(path.read_text()) for path in Path("levels").glob("*.json")]
    for x, y in [(1, 0), (0, 1), (2 ** -0.5, 2 ** -0.5),
                 (2 ** -0.5, -2 ** -0.5), (0.5 + 0.5j, 0.5 - 0.5j)]:
        for gates in ({}, {"X": 1}, {"H": 1}, {"Z": 1, "H": 1}, {"RotY": 2, "H": 1}):
            data = level(gates=gates)
            data["pillar_states"]["(2, 1)"] = {
                key: {"real": complex(value).real, "imag": complex(value).imag}
                for key, value in (("x", x), ("y", y))
            }
            cases.append(data)
    for data in cases:
        editor.game.load_level_data(data)
        assert solve_level_data(data).solvable == solve(snapshot(editor.game)).solvable


def test_desktop_job_returns_result_without_loading_game_objects():
    # The child has no display or asset access and still checks a playable level.
    job = LevelCheckJob(level(True, {"X": 1}))
    try:
        deadline = time.monotonic() + 30
        result = job.poll()
        while result is None and time.monotonic() < deadline:
            time.sleep(0.02)
            result = job.poll()
        assert result is not None and result["solvable"] is True
    finally:
        job.cancel()
