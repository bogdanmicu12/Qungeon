"""Hardware history navigation and refresh, without any quantum network calls."""

import os
import threading
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

from Qungeon import Game
from scripts.quantum_run import QuantumRun


def rows(count=12):
    return [{"request_id": f"{i:032x}", "level": i % 8 + 1, "labels": ["1,1"],
             "state": "unavailable", "backend": "Tuna-5", "created": "2026-09-18 12:00"}
            for i in range(count)]


@pytest.fixture
def game():
    game = Game(SimpleNamespace(level=1), settings={}, persist_settings=lambda _: True)
    game.menu.quantum.history = QuantumRun({}, transport=lambda _: {"state": "history", "runs": rows()})
    game.menu.quantum.history.data = {"state": "history", "runs": rows()}
    game.menu.open("quantum_history")
    game.menu.buttons()
    pygame.event.clear()
    return game


def key(game, value, **kwargs):
    game.menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=value, **kwargs))


def click(game, position):
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position))
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=position))


def test_history_scrolls_with_trackpad_and_scrollbar_and_clamps(game):
    panel = game.menu.quantum
    scroll = panel.history_scroll
    assert not any(b[2] in ("Next", "Previous") for b in game.menu.buttons())
    wheel = dict(x=0, y=-1, precise_y=-0.25, pos=scroll.rect.center, mod=0)
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, **wheel))
    assert scroll.y == 9
    wheel["pos"] = (400, 540)
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, **wheel))
    assert scroll.y == 9
    _, track, thumb = scroll.bars()[0]
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=thumb.center))
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(track.centerx, track.bottom + 100)))
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(track.centerx, track.bottom + 100)))
    assert scroll.y == scroll.max_y and scroll.drag is None
    assert scroll.rect.contains(panel.history_rect(11))
    game.menu.draw()


def test_history_keyboard_selection_scrolls_into_view(game, monkeypatch):
    panel = game.menu.quantum
    for _ in range(6):
        key(game, pygame.K_TAB)
    assert game.menu.focus == 6
    assert panel.history_scroll.rect.contains(panel.history_rect(5))
    key(game, pygame.K_END)
    assert game.menu.focus == 12 and panel.history_scroll.y == panel.history_scroll.max_y
    selected = []
    monkeypatch.setattr(game.menu, "activate", selected.append)
    key(game, pygame.K_RETURN)
    assert selected == ["quantum:history:" + rows()[-1]["request_id"]]
    key(game, pygame.K_HOME)
    assert game.menu.focus == 1 and panel.history_scroll.y == 0
    key(game, pygame.K_PAGEDOWN)
    assert panel.history_scroll.y > 0
    assert panel.history_scroll.rect.contains(panel.history_rect(game.menu.focus - 1))
    key(game, pygame.K_TAB, mod=pygame.KMOD_SHIFT)
    assert panel.history_scroll.rect.contains(panel.history_rect(game.menu.focus - 1))


def test_hidden_rows_are_clipped_for_drawing_hover_and_clicks(game, monkeypatch):
    menu, panel = game.menu, game.menu.quantum
    panel.history_scroll.move(dy=100)
    menu.draw()
    assert menu.game.screen.get_clip() == menu.game.screen.get_rect()
    # Hidden rows must not draw into the heading or the gap above the buttons.
    for rect in (pygame.Rect(60, 184, 668, 10), pygame.Rect(60, 478, 680, 17)):
        assert pygame.image.tobytes(game.screen.subsurface(rect), "RGB") == pygame.image.tobytes(menu.background.subsurface(rect), "RGB")
    selected = []
    monkeypatch.setattr(menu, "activate", selected.append)
    click(game, (400, 180))
    click(game, (400, 490))
    assert selected == []
    # The clipped first row still opens the correct saved run.
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(400, 201)))
    assert menu.focus == 2
    click(game, (400, 201))
    assert selected == ["quantum:history:" + rows()[1]["request_id"]]
    selected.clear()
    click(game, (640, 520))
    assert selected == ["quantum:refresh_history"]


def test_refresh_keeps_rows_visible_and_feedback_inside_button(game):
    panel, history = game.menu.quantum, game.menu.quantum.history
    panel.history_scroll.move(dy=90)
    game.menu.focus = len(rows()) + 1
    game.menu.draw()
    before = pygame.image.tobytes(game.screen.subsurface(panel.history_scroll.rect), "RGB")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def refresh(payload):
        calls.append(payload)
        entered.set()
        release.wait(2)
        history._reply = {"state": "history", "runs": rows()}
        finished.set()
    history._desktop_command = refresh
    try:
        game.menu.activate("quantum:refresh_history")
        assert entered.wait(1)
        game.menu.activate("quantum:refresh_history")
        assert len(calls) == 1 and history.busy
        game.menu.draw()
        after = pygame.image.tobytes(game.screen.subsurface(panel.history_scroll.rect), "RGB")
        assert after == before
        refresh_button = game.menu.buttons()[-1]
        assert refresh_button[2] == "Refreshing..." and refresh_button[1].right == 740
    finally:
        release.set()
        assert finished.wait(1)
    history.update()
    assert not history.busy and game.menu.buttons()[-1][2] == "Refresh"
    assert panel.history_scroll.y == 90


def test_refresh_preserves_visible_run_and_selection_when_new_runs_arrive(game):
    panel = game.menu.quantum
    panel.history_scroll.move(dy=3 * 68 + 10)
    game.menu.focus = 5
    old_y = panel.history_rect(3).y
    new_run = {**rows()[0], "request_id": "f" * 32}
    panel.history.data = {"state": "history", "runs": [new_run] + rows()}
    game.menu.buttons()
    assert panel.history_rect(4).y == old_y
    assert game.menu.focus == 6
    panel.history.data = {"state": "history", "runs": rows(1)}
    game.menu.buttons()
    assert panel.history_scroll.y == 0 and panel.history_scroll.bars() == []
    assert game.menu.focus == 0
    panel.history.data = {"state": "history", "runs": []}
    game.menu.draw()
    assert [b[0] for b in game.menu.buttons()] == ["back", "quantum:refresh_history"]


def test_refresh_does_not_open_a_different_run_after_pointer_down(game, monkeypatch):
    selected = []
    monkeypatch.setattr(game.menu, "activate", selected.append)
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(400, 220)))
    game.menu.quantum.history.data = {"state": "history", "runs": list(reversed(rows()))}
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(400, 220)))
    assert selected == []


def test_open_scrolled_run_and_return_preserves_position(game, monkeypatch):
    panel = game.menu.quantum
    key(game, pygame.K_END)
    position = panel.history_scroll.y
    requests = []
    monkeypatch.setattr(QuantumRun, "command", lambda self, action: requests.append((self.request_id, action)))
    click(game, panel.history_rect(11).center)
    assert game.menu.page == "quantum"
    assert requests[-1] == (rows()[-1]["request_id"], "status")
    game.menu.back()
    assert game.menu.page == "quantum_history" and panel.history_scroll.y == position
    assert requests[-1][1] == "history"


def test_initial_loading_and_failed_refresh_are_clear(game, monkeypatch):
    panel = game.menu.quantum
    labels = []
    monkeypatch.setattr(game.menu, "text", lambda value, *args, **kwargs: labels.append(value))
    panel.history.data = {"state": "idle"}
    panel.history.busy = True
    game.menu.draw()
    assert "Refreshing..." in labels and "Loading runs..." not in labels
    assert not any("No hardware runs" in value for value in labels)
    labels.clear()
    panel.history.busy = False
    panel.history.data = {"state": "history", "runs": rows(), "message": "Connection interrupted."}
    game.menu.draw()
    assert "Could not refresh runs. Try Refresh again." in labels
    assert any(value.startswith("Level ") for value in labels)
    assert "Loading runs..." not in labels
