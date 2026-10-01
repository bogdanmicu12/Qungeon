"""Checks for the level solver (scripts/level_solver.py).

The point of these tests is not that the solver returns *an* answer, but that
its answers match reality:

* every shipped level is reported solvable, and the plan it returns is then
  replayed into a real `Game` and *walked to the END tile using the game's own
  movement code* - so a plan that only looks right on paper fails here;
* several hand-verified dead ends (argued in each test's docstring) are
  reported unsolvable, including one that turns on relative phase and one that
  turns on entanglement;
* the walkability rule is compared against `QuantumObject.function` pillar by
  pillar, so the solver cannot drift from the game.

Run with the project environment:
    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_solver.py -q
"""

import json
import os
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pygame
import pytest

from Qungeon import Game
from scripts import level_solver
from scripts.game_objects import QuantumObject, control_gates, gates

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
SHIPPED_LEVELS = range(1, 9)

DIRECTIONS = {
    (1, 0): pygame.K_d,
    (-1, 0): pygame.K_a,
    (0, 1): pygame.K_s,
    (0, -1): pygame.K_w,
}

OPPOSITE = {
    pygame.K_d: pygame.K_a,
    pygame.K_a: pygame.K_d,
    pygame.K_s: pygame.K_w,
    pygame.K_w: pygame.K_s,
}


@pytest.fixture
def game():
    """A real Game on level 1; individual tests load whichever level they need."""
    game = Game(
        SimpleNamespace(level=1),
        settings={},
        persist_settings=lambda _: True,
    )
    game.run_mode = "single"
    pygame.event.clear()
    yield game
    pygame.event.clear()


def load(game, level):
    """Load a shipped level number or a fixture filename into `game`."""
    if isinstance(level, int):
        game.load_level(f"./levels/{level}.json")
    else:
        game.load_level(os.path.join(FIXTURES, level))
    return game


def key_of(position):
    return f"{position[0]},{position[1]}"


def replay(game, plan):
    """Apply a solver plan to a real Game, through the game's own methods.

    Moves and loot pickups are walked with the game's movement code, and every
    gate must be within the player's reach, so a plan that stands in the wrong
    place fails here.
    """
    for action in plan:
        if action[0] in ("move", "loot"):
            assert walk_to(game, action[1]), action
            continue

        _, name, pillar, target = action
        obj = game.objects[key_of(pillar)]

        assert game.player.distance(*pillar), action

        if name == "SWAP":
            game.swap_pillars(obj, game.objects[key_of(target)])
        elif name in control_gates:
            obj.apply_effect(
                game,
                [level_solver.CONTROL_EFFECTS[name], target],
            )
        else:
            obj.apply_effect(game, gates[name])

        game.hotbar.remove_by_key(name)


def assert_same_state(first, second):
    """Same inventory, loot and blocks, with amplitudes equal up to global phase.

    The game simulates in single precision and the solver in double, so block
    vectors are compared by fidelity rather than byte for byte.
    """
    assert first.inventory == second.inventory
    assert first.loot == second.loot

    blocks = {block.qubits: block.vector for block in second.blocks}

    assert sorted(block.qubits for block in first.blocks) == sorted(blocks)

    for block in first.blocks:
        overlap = abs(np.vdot(block.vector, blocks[block.qubits]))
        assert overlap == pytest.approx(1.0, abs=1e-6), block.qubits


def walk_to_end(game):
    """Try to walk the player to the END tile using only the game's own moves.

    Nothing about walls, pillars or loot is re-implemented here: each candidate
    step is handed to `Game.update_position` and the hop is finished with
    `update_hop`, exactly as the real game loop would. A step the game refuses
    simply leaves the player where they were. Backtracking is safe because
    movement in this game is reversible.
    """
    return _explore(
        game,
        {tuple(game.player.position)},
        lambda: game.menu.page == "complete",
    )


def walk_to(game, target):
    """Walk the player onto `target` with the game's own moves, like walk_to_end."""
    return tuple(game.player.position) == target or _explore(
        game,
        {tuple(game.player.position)},
        lambda: tuple(game.player.position) == target,
    )


def _explore(game, seen, done):
    origin = tuple(game.player.position)

    for delta, key in DIRECTIONS.items():
        destination = (
            origin[0] + delta[0],
            origin[1] + delta[1],
        )

        if destination in seen:
            continue

        seen.add(destination)

        game.update_position(key)
        game.update_hop(100)

        if done():
            return True

        if tuple(game.player.position) != destination:
            continue

        if _explore(game, seen, done):
            return True

        game.update_position(OPPOSITE[key])
        game.update_hop(100)

    return False


# --------------------------------------------------------------------------
# The shipped levels
# --------------------------------------------------------------------------

@pytest.mark.parametrize("level", SHIPPED_LEVELS)
def test_shipped_level_is_solvable(game, level):
    load(game, level)
    assert level_solver.solve(
        level_solver.snapshot(game)
    ).solvable is True


@pytest.mark.parametrize("level", SHIPPED_LEVELS)
def test_returned_plan_actually_wins_in_the_game(game, level):
    """End-to-end: replay the plan, then walk to END with the real game rules.

    This is the test that would catch a wrong gate matrix, a mixed-up control
    and target, or a walkability rule that has drifted from the game's.
    """
    load(game, level)

    solution = level_solver.solve(
        level_solver.snapshot(game)
    )

    assert solution.solvable is True

    replay(game, solution.plan)

    assert walk_to_end(game), (
        f"level {level}: solver plan did not reach END"
    )

    assert game.menu.page == "complete"


@pytest.mark.parametrize("level", SHIPPED_LEVELS)
def test_walkability_matches_the_game(game, level):
    """The solver's pure-|0> test must agree with QuantumObject.function.

    Checked both at the start (where pillars block) and after the plan has been
    replayed (where they no longer do), so both answers are exercised rather
    than just the blocking one.
    """
    load(game, level)

    blocked = _compare_walkability(game)

    assert False in blocked, (
        f"level {level}: expected some pillar to block"
    )

    replay(
        game,
        level_solver.solve(
            level_solver.snapshot(game)
        ).plan,
    )

    assert True in _compare_walkability(game), (
        f"level {level}: nothing was cleared"
    )


def _compare_walkability(game):
    """Assert solver and game agree on every pillar; return the answers seen."""
    state = level_solver.snapshot(game)
    answers = []

    for obj in game.objects.values():
        if isinstance(obj, QuantumObject):
            position = obj.position
            expected = obj.function(game, *position)

            assert (
                state.block_of(position).walkable(position)
                is expected
            ), position

            answers.append(expected)

    return answers


# --------------------------------------------------------------------------
# Known dead ends
# --------------------------------------------------------------------------

def test_two_pillars_need_two_gates(game):
    """One X cannot clear two |1> pillars; two X can, in order.

    The solvable variant also pins the adjacency rule: (6,4) is two tiles from
    anywhere the player can stand until (5,4) has been cleared and stepped on.
    """
    load(game, "two_pillars_one_gate.json")

    assert level_solver.solve(
        level_solver.snapshot(game)
    ).solvable is False

    load(game, "two_pillars_two_gates.json")

    solution = level_solver.solve(
        level_solver.snapshot(game)
    )

    assert solution.solvable is True

    replay(game, solution.plan)

    assert walk_to_end(game)


def test_controlled_gate_may_target_an_out_of_reach_pillar(game):
    """A pillar too far away to drop a gate on can still be a CNOT target.

    In this level the far pillar (6,4) is never adjacent to a walkable tile
    while the near pillar (4,4) blocks the corridor, and the single X is needed
    for the near pillar - so the only way through is a CNOT controlled by the
    near pillar (which starts |1>) onto the far one.
    """
    load(game, "remote_target.json")

    state = level_solver.snapshot(game)

    region = level_solver.reachable(state)
    in_reach = level_solver._reachable_pillars(
        state,
        region,
    )

    assert (4, 4) in in_reach
    assert (6, 4) not in in_reach

    solution = level_solver.solve(state)

    assert solution.solvable is True
    assert (
        "gate",
        "CNOT",
        (4, 4),
        (6, 4),
    ) in solution.plan

    replay(game, solution.plan)

    assert walk_to_end(game)


def test_swap_plan_actually_wins_in_the_game(game):
    """SWAP is the only way past a |1> pillar when a free |0> pillar exists.

    The swap partner (4,6) is out of reach, which SWAP allows just like the
    target of a controlled gate.
    """
    load(game, "swap_needed.json")

    solution = level_solver.solve(
        level_solver.snapshot(game)
    )

    assert solution.plan == (
        ("gate", "SWAP", (4, 4), (4, 6)),
    )

    replay(game, solution.plan)

    assert walk_to_end(game)


def test_level_1_swap_route_is_found_after_x_on_the_corridor_pillar(game):
    """X on (5,4) opens the corridor to the SWAP chest; the level is still winnable.

    Take the SWAP at (6,4), walk back to (4,4) and swap the cleared (5,4) with
    the |1> pillar (4,5) that blocks the way down. Using SWAP from the chest
    tile instead would re-block (5,4) and trap the player in the dead end, so
    the solver must consider where the player stands when spending a gate.
    """
    load(game, 1)

    game.objects["5,4"].apply_effect(game, gates["X"])
    game.hotbar.remove_by_key("X")

    solution = level_solver.solve(level_solver.snapshot(game))

    assert solution.solvable is True
    assert ("loot", (6, 4), "SWAP") in solution.plan

    replay(game, solution.plan)

    assert walk_to_end(game)

    # The same holds once the chest has been taken and the player stands on it.
    load(game, 1)

    game.objects["5,4"].apply_effect(game, gates["X"])
    game.hotbar.remove_by_key("X")

    assert walk_to(game, (6, 4))
    assert level_solver.is_solvable(game) is True


def test_swap_moves_entanglement_without_growing_blocks(game):
    """Swapping one half of a Bell pair moves the entanglement with it.

    The game's groups must follow, or `snapshot` cannot factor the state along
    them; and the solver's own SWAP must not merge unrelated blocks.
    """
    load(game, "swap_entangled.json")

    predicted = level_solver._apply_gate(
        level_solver.snapshot(game),
        "SWAP",
        (4, 4),
        (4, 6),
    )

    replay(game, (("gate", "SWAP", (4, 4), (4, 6)),))

    assert sorted(
        sorted(obj.position for obj in group.objects)
        for group in game.grouping_system.groups
    ) == [[(4, 4)], [(4, 6), (5, 4)]]

    after = level_solver.snapshot(game)

    assert sorted(block.qubits for block in after.blocks) == [
        ((4, 4),),
        ((4, 6), (5, 4)),
    ]

    assert_same_state(predicted, after)

    _compare_walkability(game)


def test_swap_moves_the_phase_colour_with_the_state(game):
    """|-> and |+> look alike in probabilities; only `phase_Z` tells them apart.

    After swapping |-> onto a |0> pillar, the receiving pillar must show |->,
    not |+>, and the emptied one must lose the phase tint.
    """
    load(game, "swap_needed.json")

    minus = game.objects["4,4"]
    zero = game.objects["4,6"]

    minus.apply_effect(game, gates["H"])  # |1> -> |->

    assert minus.phase_Z is True

    replay(game, (("gate", "SWAP", (4, 4), (4, 6)),))

    assert zero.phase_Z is True
    assert minus.phase_Z is False
    assert minus.color == (255, 255, 255)


@pytest.mark.parametrize(
    "level",
    [*SHIPPED_LEVELS, "swap_needed.json", "swap_entangled.json"],
)
def test_level_data_state_matches_the_game(game, level):
    """`state_from_level_data` must build the same state as loading the level."""
    load(game, level)

    path = (
        f"./levels/{level}.json"
        if isinstance(level, int)
        else os.path.join(FIXTURES, level)
    )

    with open(path, encoding="utf-8") as file:
        from_data = level_solver.state_from_level_data(json.load(file))

    assert_same_state(from_data, level_solver.snapshot(game))


def test_wasting_a_gate_makes_level_2_unsolvable(game):
    """Level 2 is |+> then |1>; X on |+> is a no-op and burns the X.

    X|+> = |+>, so after this the only remaining gate is H: it can clear the
    superposed pillar, but nothing is left for the |1> pillar behind it.
    """
    load(game, 2)

    assert level_solver.solve(
        level_solver.snapshot(game)
    ).solvable is True

    game.objects["5,4"].apply_effect(
        game,
        gates["X"],
    )
    game.hotbar.remove_by_key("X")

    assert level_solver.solve(
        level_solver.snapshot(game)
    ).solvable is False


def test_relative_phase_matters_on_level_3(game):
    """Level 3's pillar is |->, and only H-then-X clears it.

    X|-> = -|->, which is the same state up to global phase, so spending the X
    first wastes it: H then turns |-> into |1>, and no gate is left to flip it.
    A solver that ignored relative phase would think |-> behaves like |+> and
    call this solvable.
    """
    load(game, 3)

    assert level_solver.solve(
        level_solver.snapshot(game)
    ).solvable is True

    game.objects["5,4"].apply_effect(
        game,
        gates["X"],
    )
    game.hotbar.remove_by_key("X")

    assert level_solver.solve(
        level_solver.snapshot(game)
    ).solvable is False


def test_wasted_cnots_make_entangled_level_8_unsolvable(game):
    """Level 8's three pillars start in a GHZ state; two CNOTs and an H fix it.

    Applying the same CNOT twice is the identity, so this leaves the GHZ state
    intact with only H remaining. No single-qubit gate turns GHZ into a product
    state, so every pillar keeps P(|0>) = 1/2 and the corridor stays shut.
    """
    load(game, 8)

    assert level_solver.solve(
        level_solver.snapshot(game)
    ).solvable is True

    control = game.objects["4,3"]

    for _ in range(2):
        control.apply_effect(
            game,
            [
                level_solver.CONTROL_EFFECTS["CNOT"],
                (5, 3),
            ],
        )
        game.hotbar.remove_by_key("CNOT")

    assert level_solver.solve(
        level_solver.snapshot(game)
    ).solvable is False


# --------------------------------------------------------------------------
# Contracts the solver has to keep as the game grows
# --------------------------------------------------------------------------

def test_every_gate_the_game_offers_is_supported():
    """Fails when a supported gate is not taught to the solver."""
    for name in gates:
        if name == "SWAP":
            continue

        matrix = level_solver.gate_unitary(name)

        assert matrix.shape == (
            2,
            2,
        ), f"{name}: expected a single-qubit gate"

    # SWAP is a real two-qubit operation, so it deliberately has no 2x2
    # gate_unitary. It must still be accepted by the search implementation.
    assert "SWAP" in gates

    for name in control_gates:
        if name == "SWAP":
            continue

        assert name in level_solver.CONTROL_EFFECTS, (
            f"controlled gate {name!r} has no entry in "
            "level_solver.CONTROL_EFFECTS; add the effect it applies "
            "to its target (see Game.handle_object_dragging)"
        )


def test_budget_exhaustion_reports_unknown_never_stuck(game):
    """Running out of budget must not be mistaken for an unwinnable level."""
    load(game, 6)

    solution = level_solver.solve(
        level_solver.snapshot(game),
        budget=5,
    )

    assert solution.solvable is None
    assert solution.is_stuck is False


def test_is_solvable_reads_the_live_game(game):
    """The public entry point works straight off a Game instance."""
    load(game, 1)

    assert level_solver.is_solvable(game) is True
    game.hotbar.remove_by_key("X")            # level 1's only gate
    assert level_solver.is_solvable(game) is False


def test_equivalent_states_hash_together_despite_negative_zero():
    """Rounding can leave -0.0, whose bytes differ from +0.0.

    Two vectors that compare equal must share a cache key, or the search
    re-explores the same state and can burn its budget into a false "unknown".
    """
    import numpy as np

    # The tiny amplitude is below _PHASE_EPS, so it is not the phase reference
    # and survives normalisation to be rounded away - to -0.0 in one case.
    rounds_to_negative_zero = np.array([1 + 0j, -1e-12j], dtype=np.complex128)
    rounds_to_positive_zero = np.array([1 + 0j, +1e-12j], dtype=np.complex128)

    assert (level_solver._canonical_vector(rounds_to_negative_zero)
            == level_solver._canonical_vector(rounds_to_positive_zero))
