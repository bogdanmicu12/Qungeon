"""Numerical state checks and real game input for the live Bloch inspector."""

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import cirq
import numpy as np
import pygame
import pytest

from scripts.bloch_state import BlochStateCache


Q = cirq.LineQubit(0)


@pytest.mark.parametrize("operations,expected,name", [
    ([], (0, 0, 1), "|0>"),
    ([cirq.X(Q)], (0, 0, -1), "|1>"),
    ([cirq.H(Q)], (1, 0, 0), "|+>"),
    ([cirq.H(Q), cirq.Z(Q)], (-1, 0, 0), "|->"),
    ([cirq.H(Q), cirq.S(Q)], (0, 1, 0), "|+i>"),
    ([cirq.H(Q), cirq.S(Q)**-1], (0, -1, 0), "|-i>"),
    ([cirq.H(Q), cirq.H(Q)], (0, 0, 1), "|0>"),
])
def test_basis_states_and_phase(operations, expected, name):
    state = BlochStateCache().read(cirq.Circuit(operations), [Q])[Q]
    np.testing.assert_allclose(state.vector, expected, atol=1e-7)
    assert state.purity == pytest.approx(1)
    assert state.description == f"Pure state {name}"
    assert state.probability_zero == pytest.approx((1+expected[2])/2)


def test_fractional_rotation_and_global_phase():
    circuit = cirq.Circuit(cirq.ry(0.723)(Q), cirq.rz(-0.41)(Q))
    cache = BlochStateCache()
    before = cache.read(circuit, [Q])[Q]
    np.testing.assert_allclose(before.vector,
        (np.sin(0.723)*np.cos(-0.41), np.sin(0.723)*np.sin(-0.41), np.cos(0.723)), atol=1e-7)
    circuit.append(cirq.global_phase_operation(1j))
    np.testing.assert_allclose(cache.read(circuit, [Q])[Q].vector, before.vector, atol=1e-7)


def test_bell_state_and_qubit_mapping_including_untouched_pillars():
    a, b, untouched = cirq.NamedQubit("9,1"), cirq.NamedQubit("10,1"), cirq.NamedQubit("0,0")
    cache = BlochStateCache()
    circuit = cirq.Circuit(cirq.H(a), cirq.CNOT(a, b))
    states = cache.read(circuit, [b, untouched, a])
    for qubit in (a, b):
        np.testing.assert_allclose(states[qubit].vector, (0, 0, 0), atol=1e-7)
        assert states[qubit].purity == pytest.approx(0.5)
        assert states[qubit].description == "Mixed local state"
    assert states[untouched].probability_zero == 1
    circuit.append(cirq.CNOT(a, b))
    states = cache.read(circuit, [b, untouched, a])
    assert states[a].description == "Pure state |+>"
    assert states[b].description == "Pure state |0>"


def test_partially_entangled_state_stays_inside_sphere():
    a, b = cirq.LineQubit.range(2)
    states = BlochStateCache().read(cirq.Circuit(cirq.ry(np.pi/3)(a), cirq.CNOT(a, b)), [a, b])
    for state in states.values():
        np.testing.assert_allclose(state.vector, (0, 0, 0.5), atol=1e-7)
        assert state.probability_zero == pytest.approx(0.75)
        assert state.purity == pytest.approx(0.625)


def test_circuit_mutation_invalidates_cached_state(monkeypatch):
    calls = []
    simulate = cirq.Simulator.simulate
    monkeypatch.setattr(cirq.Simulator, "simulate", lambda *a, **kw: calls.append(1) or simulate(*a, **kw))
    cache, circuit = BlochStateCache(), cirq.Circuit(cirq.H(Q))
    before = cache.read(circuit, [Q])
    for _ in range(60):
        assert cache.read(circuit, [Q]) is before
    assert len(calls) == 1
    circuit.append(cirq.Z(Q))
    assert cache.read(circuit, [Q])[Q].description == "Pure state |->"
    assert before[Q].description == "Pure state |+>"  # history remains immutable
    assert len(calls) == 2


@pytest.mark.parametrize("operation", [cirq.measure(Q), cirq.depolarize(0.1)(Q)])
def test_nonunitary_states_are_not_presented_as_exact_pure_states(operation):
    cache = BlochStateCache()
    for _ in range(2):
        with pytest.raises(ValueError, match="unitary"):
            cache.read(cirq.Circuit(operation), [Q])
    assert cache.read(cirq.Circuit(cirq.X(Q)), [Q])[Q].description == "Pure state |1>"


@pytest.fixture
def game(monkeypatch):
    from Qungeon import Game
    game = Game(SimpleNamespace(level=2), settings={}, persist_settings=lambda _: True)
    game.start_level(2)
    game.settings["stuck_warning"] = False
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (0, 0))
    pygame.event.clear()
    yield game
    pygame.event.clear()


def event(game, kind, **fields):
    pygame.event.post(pygame.event.Event(kind, **fields))
    game.handle_events()


def key(game, value, mod=0):
    event(game, pygame.KEYDOWN, key=value, mod=mod)


def click(game, position):
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        event(game, kind, button=1, pos=position)


def test_keyboard_and_hover_inspection_preserve_game_state(game):
    initial = (game.quantum_grid.circuit.copy(), game.resource_signature(), game.player.position)
    key(game, pygame.K_b)
    assert game.bloch.selected is game.objects["5,4"]
    event(game, pygame.MOUSEMOTION, pos=game.objects["6,4"].rect.center)
    assert game.bloch.selected is game.objects["6,4"]
    event(game, pygame.MOUSEMOTION, pos=game.objects["5,4"].rect.center)
    assert game.bloch.selected is game.objects["5,4"]
    key(game, pygame.K_TAB)
    assert game.bloch.selected is game.objects["6,4"]
    key(game, pygame.K_TAB, pygame.KMOD_SHIFT)
    assert game.bloch.selected is game.objects["5,4"]
    assert initial == (game.quantum_grid.circuit, game.resource_signature(), game.player.position)


def test_help_and_close_clicks_do_not_reach_gameplay(game, monkeypatch):
    key(game, pygame.K_b)
    monkeypatch.setattr(game.hotbar, "handle_mouse_up", lambda *args: pytest.fail("Inspector release leaked"))
    monkeypatch.setattr(game, "handle_object_dragging", lambda *args: pytest.fail("Inspector press leaked"))
    click(game, game.bloch.buttons()["help"].center)
    assert game.bloch.help_open
    click(game, game.bloch.buttons()["close"].center)
    assert not game.bloch.enabled


def test_keyboard_gate_application_retains_correct_before_and_after(game):
    key(game, pygame.K_b)
    game.player.update_position(4, 4)
    key(game, pygame.K_2)  # select H, then walk towards the pillar
    key(game, pygame.K_d)
    pillar = game.objects["5,4"]
    assert game.bloch.previous[pillar.qubit].description == "Pure state |+>"
    assert game.bloch.states()[pillar.qubit].description == "Pure state |0>"
    assert game.bloch.last_gate == "H"
    assert game.bloch.states()[pillar.qubit].probability_zero >= 1-1e-6
    assert pillar.function(game, 5, 4)


def test_controlled_gate_passes_through_panel_and_updates_both_states(game):
    game.start_level(8)
    key(game, pygame.K_b)
    control, target = game.objects["4,3"], game.objects["5,3"]
    game.bloch.select(target)
    game.bloch.rect.topleft = (180, 100)  # panel covers both control and target
    game.player.update_position(3, 3)
    game.hotbar.slots["CNOT"].dragging = True
    assert game.bloch.visible() and game.bloch.dragging()
    event(game, pygame.MOUSEBUTTONUP, button=1, pos=control.rect.center)
    assert control.dragging and game.bloch.visible()
    click(game, target.rect.center)
    assert game.bloch.visible() and game.bloch.last_gate == "CNOT"
    assert game.bloch.previous[target.qubit].description == "Mixed local state"
    assert game.bloch.states()[target.qubit].description == "Pure state |0>"
    assert game.bloch.states()[control.qubit].description == "Mixed local state"
    assert game.hotbar.slots["CNOT"].count == 1


def test_toggle_and_help_cancel_unfinished_drags_without_spending_gate(game):
    for button in (pygame.K_b, pygame.K_h):
        game.hotbar.slots["H"].dragging = True
        key(game, button)
        assert not game.hotbar.slots["H"].dragging
        assert game.hotbar.slots["H"].count == 1
    assert game.gate_help_open and not game.bloch.visible()
    key(game, pygame.K_b)
    assert game.bloch.enabled  # B is ignored inside the gate guide


def test_pause_resume_restart_and_new_level(game):
    key(game, pygame.K_b)
    selected = game.bloch.selected
    key(game, pygame.K_ESCAPE)
    assert not game.bloch.visible()
    key(game, pygame.K_ESCAPE)
    assert game.bloch.selected is selected
    key(game, pygame.K_r)
    assert game.bloch.enabled
    assert game.bloch.selected is None and not game.bloch.previous
    game.display_game()
    assert game.bloch.selected is not selected
    game.start_level(8)
    assert not game.bloch.previous and game.bloch.last_gate is None


def test_inspector_disabled_has_no_simulation_cost(game, monkeypatch):
    monkeypatch.setattr(game.bloch, "states", lambda: pytest.fail("Disabled inspector simulated"))
    from scripts.game_objects import gates
    game.objects["5,4"].apply_effect(game, gates["Z"])
    game.display_game()


@pytest.mark.parametrize("help_open", [False, True])
@pytest.mark.parametrize("level", sorted(int(path.stem) for path in Path("levels").glob("*.json") if path.stem.isdigit()))
def test_panel_and_text_fit_canvas_without_covering_selected_pillar(game, monkeypatch, help_open, level):
    from scripts.common_functions import font
    game.start_level(level)
    assert game.menu.page == "playing" and game.current_level == level
    key(game, pygame.K_b)
    game.bloch.help_open = help_open
    original_text = game.bloch.text
    def checked_text(text, x, y, size=18, color=(0, 0, 0), centered=False):
        rect = font(size).render(text, True, color).get_rect()
        if centered:
            rect.midtop = (x, y)
        else:
            rect.topleft = (x, y)
        assert game.bloch.rect.contains(rect), (text, rect, game.bloch.rect)
        return original_text(text, x, y, size, color, centered)
    monkeypatch.setattr(game.bloch, "text", checked_text)
    for pillar in game.bloch.pillars():
        game.bloch.select(pillar)
        game.display_game()
        assert pygame.Rect(0, 108, 800, 417).contains(game.bloch.rect)
        assert not game.bloch.rect.colliderect(pillar.rect)


def test_empty_level_and_unsupported_state_do_not_break_game(game):
    key(game, pygame.K_b)
    game.quantum_grid.circuit.append(cirq.measure(game.bloch.selected.qubit))
    game.display_game()  # explicit unavailable panel, not a crash
    game.objects.clear()
    game.display_game()
    assert game.bloch.selected is None
    key(game, pygame.K_TAB)


def test_initial_edges_align_with_header_divider(game):
    from scripts.menus import HEADER_LEFT, HEADER_RIGHT
    game.objects["5,4"].rect.centerx = 300
    key(game, pygame.K_b)
    assert game.bloch.rect.right == HEADER_RIGHT
    right_pillar = game.objects["6,4"]
    right_pillar.rect.centerx = 600
    game.bloch.select(right_pillar)
    assert game.bloch.rect.left == HEADER_LEFT


def start_panel_drag(game):
    key(game, pygame.K_b)
    position = (game.bloch.rect.x+25, game.bloch.rect.y+18)
    event(game, pygame.MOUSEBUTTONDOWN, button=1, pos=position)
    assert game.bloch.drag_offset == (25, 18)
    return position


def test_drag_preserves_state_and_placement_across_selection_and_reopening(game, monkeypatch):
    initial = (game.quantum_grid.circuit.copy(), game.resource_signature(), game.player.position)
    position = start_panel_drag(game)
    selected = game.bloch.selected
    monkeypatch.setattr(game, "handle_object_dragging", lambda *args: pytest.fail("Panel press leaked"))
    monkeypatch.setattr(game.hotbar, "handle_mouse_up", lambda *args: pytest.fail("Panel release leaked"))
    destination = (388 + 25, 170 + 18)
    event(game, pygame.MOUSEMOTION, pos=destination, buttons=(1, 0, 0))
    game.bloch.update_hover(game.objects["6,4"].rect.center)
    assert game.bloch.selected is selected
    assert game.bloch.rect.topleft == (388, 170)
    # Movement and gate shortcuts must not act on the puzzle during a panel drag.
    key(game, pygame.K_2)
    key(game, pygame.K_d)
    event(game, pygame.MOUSEBUTTONUP, button=1, pos=destination)
    assert game.bloch.drag_offset is None and not game.bloch.mouse_captured
    assert initial == (game.quantum_grid.circuit, game.resource_signature(), game.player.position)
    assert game.hotbar.selected_key is None
    game.objects["6,4"].rect.centerx = 600
    key(game, pygame.K_TAB)
    assert game.bloch.rect.topleft == (388, 170)
    key(game, pygame.K_b)
    key(game, pygame.K_b)
    assert game.bloch.rect.topleft == (388, 170)
    game.restart_level()
    assert not game.bloch.manually_positioned
    assert game.bloch.rect.topleft == (488, 110)


@pytest.mark.parametrize("destination", [(-1000, -1000), (2000, 2000)])
def test_drag_clamps_to_canvas_and_consumes_release_outside_panel(game, destination):
    start_panel_drag(game)
    event(game, pygame.MOUSEBUTTONUP, button=1, pos=destination)
    assert game.screen.get_rect().inflate(-16, -16).contains(game.bloch.rect)
    assert game.bloch.drag_offset is None and not game.bloch.mouse_captured


@pytest.mark.parametrize("action", [pygame.K_ESCAPE, pygame.K_h, pygame.K_b, pygame.K_r])
def test_screen_transitions_cancel_panel_drag(game, action):
    start_panel_drag(game)
    key(game, action)
    assert game.bloch.drag_offset is None
    position = game.bloch.rect.topleft
    event(game, pygame.MOUSEMOTION, pos=(400, 400), buttons=(1, 0, 0))
    assert game.bloch.rect.topleft == position


def test_lost_pointer_release_stops_dragging(game):
    start_panel_drag(game)
    event(game, pygame.MOUSEMOTION, pos=(400, 400), buttons=(0, 0, 0))
    assert game.bloch.drag_offset is None and not game.bloch.mouse_captured


def test_header_buttons_do_not_start_panel_drag(game):
    key(game, pygame.K_b)
    for action in ("help", "close"):
        click(game, game.bloch.buttons()[action].center)
        assert game.bloch.drag_offset is None


def test_panel_fades_during_gate_drag_then_restores_opacity(game):
    from scripts.menus import BG, PANEL
    key(game, pygame.K_b)
    point = (game.bloch.rect.x+5, game.bloch.rect.y+70)
    game.display_game()
    assert tuple(game.screen.get_at(point)[:3]) == PANEL
    game.hotbar.slots["H"].dragging = True
    game.display_game()
    faded = game.screen.get_at(point)[:3]
    assert all(background < value < foreground for background, value, foreground in zip(BG, faded, PANEL))
    game.cancel_dragging()
    game.display_game()
    assert tuple(game.screen.get_at(point)[:3]) == PANEL


def test_keyboard_selection_survives_stationary_mouse_without_pinning(game, monkeypatch):
    key(game, pygame.K_b)
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: game.objects["5,4"].rect.center)
    key(game, pygame.K_TAB)
    game.display_game()
    assert game.bloch.selected is game.objects["6,4"]
    event(game, pygame.MOUSEMOTION, pos=game.objects["5,4"].rect.center)
    assert game.bloch.selected is game.objects["5,4"]


def test_swap_drag_updates_both_states_and_preserves_inventory_rules(game):
    from scripts.game_objects import gates

    control, target = game.objects["5,4"], game.objects["6,4"]
    target.apply_effect(game, gates["X"])
    game.hotbar.add_item("SWAP", 1)
    game.player.update_position(4, 4)
    key(game, pygame.K_b)
    before = game.bloch.states()
    game.bloch.rect.topleft = (180, 100)
    game.hotbar.slots["SWAP"].dragging = True
    event(game, pygame.MOUSEBUTTONUP, button=1, pos=control.rect.center)
    assert control.dragging
    click(game, target.rect.center)

    assert game.bloch.last_gate == "SWAP"
    assert game.bloch.previous == before
    assert game.bloch.states()[control.qubit] == before[target.qubit]
    assert game.bloch.states()[target.qubit] == before[control.qubit]
    assert "SWAP" not in game.hotbar.slots


def test_shared_editor_states_and_seed_levels_reset_the_inspector(game):
    from scripts.level_share import encode_level

    key(game, pygame.K_b)
    data = {
        "editor_created": True,
        "tiles": {"(1, 1)": "START", "(2, 1)": "EMPTY", "(3, 1)": "END"},
        "objects": {}, "quantum_objects": ["(2, 1)"],
        "pillar_states": {"(2, 1)": {
            "x": {"real": 2**-0.5, "imag": 0},
            "y": {"real": 0, "imag": 2**-0.5},
        }},
        "gates": {"X": 1}, "effects": [],
    }
    game.start_seed_level(encode_level(data))
    game.display_game()
    assert game.bloch.enabled and not game.bloch.previous
    assert game.bloch.states()[game.objects["2,1"].qubit].description == "Pure state |+i>"
    game.restart_level()
    assert game.bloch.selected is None
    assert game.bloch.states()[game.objects["2,1"].qubit].description == "Pure state |+i>"
    game.start_seed_level("QG-000000000000002A")
    game.display_game()
    assert game.bloch.visible() and not game.bloch.previous
    assert set(game.bloch.states()) == {pillar.qubit for pillar in game.bloch.pillars()}
    game.open_editor()
    key(game, pygame.K_b)
    assert not game.bloch.visible() and game.bloch.enabled


def test_gate_selector_and_footer_remain_clear_with_the_inspector(game, monkeypatch):
    from scripts.common_functions import font

    draw_selection_panel = game.hotbar.draw_selection_panel
    panel_draws = []

    def track_selection_panel(screen):
        panel_draws.append(True)
        draw_selection_panel(screen)

    monkeypatch.setattr(game.hotbar, "draw_selection_panel", track_selection_panel)
    game.display_game()
    assert len(panel_draws) == 1
    bottom_before = pygame.image.tobytes(game.screen.subsurface((0, 525, 800, 75)), "RGB")
    key(game, pygame.K_b)
    game.display_game()
    assert len(panel_draws) == 2
    assert pygame.image.tobytes(game.screen.subsurface((0, 525, 800, 75)), "RGB") == bottom_before

    labels = []
    def record_text(text, x, y, size=22, color=None, centered=False):
        rect = pygame.Rect((0, 0), font(size).size(text))
        if centered:
            rect.midtop = (x, y)
        else:
            rect.topleft = (x, y)
        labels.append((text, rect))

    monkeypatch.setattr(game.menu, "text", record_text)
    game.show_quantum_notice("H was selected")
    game.menu.draw_hud()
    assert any(text == "B  Bloch sphere" for text, _ in labels)
    for index, (text, rect) in enumerate(labels):
        assert game.screen.get_rect().contains(rect), text
        for other_text, other_rect in labels[index+1:]:
            assert not rect.colliderect(other_rect), (text, other_text)
    game.bloch.select(game.objects["6,4"])
    game.bloch.rect.x = 40
    assert all(not game.bloch.rect.colliderect(rect) for _, rect in labels)


def test_gate_drag_keeps_main_hotbar_working_above_the_inspector(game):
    slot = game.hotbar.slots["H"]
    game.display_game()
    position = game.hotbar.selection_rects["H"].center
    event(game, pygame.MOUSEBUTTONDOWN, button=1, pos=position)
    assert slot.dragging
    event(game, pygame.MOUSEBUTTONUP, button=1, pos=(0, 0))
    assert not slot.dragging and slot.count == 1
    key(game, pygame.K_b)
    game.player.update_position(4, 4)
    pillar = game.objects["5,4"]
    game.bloch.rect.topleft = (180, 100)
    event(game, pygame.MOUSEBUTTONDOWN, button=1, pos=game.hotbar.selection_rects["H"].center)
    event(game, pygame.MOUSEBUTTONUP, button=1, pos=pillar.rect.center)
    assert "H" not in game.hotbar.slots
    assert game.bloch.last_gate == "H"
    assert game.bloch.states()[pillar.qubit].description == "Pure state |0>"
