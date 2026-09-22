"""Runnable check for deterministic walkability (QUN-5).

Needs pygame + unitary + cirq, so it skips cleanly if they're unavailable.
Run with the project venv:
    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python tests/test_walkability.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

try:
    import pygame
    pygame.display.init()
    pygame.font.init()
    pygame.display.set_mode((800, 600))
    from Qungeon import Game
    from scripts.game_objects import gates
except Exception as exc:  # pragma: no cover - environment without deps
    print(f"SKIP test_walkability: {type(exc).__name__}: {exc}")
    sys.exit(0)


def test_pure_zero_is_passable():
    g = Game(argparse.Namespace(level=1))
    pillar = g.objects["5,4"]        # starts |1> (Flip in level 1)
    pillar.apply_effect(g, gates["X"])  # -> |0>
    assert pillar.function(g, 5, 4) is True


def test_level2_is_solvable():
    """Two-qubit worlds round to ~0.9999999 in cirq's complex64 sim, so a
    tolerance tighter than that makes every multi-pillar level unwinnable."""
    g = Game(argparse.Namespace(level=2))
    superposed, flipped = g.objects["5,4"], g.objects["6,4"]
    superposed.apply_effect(g, gates["H"])  # H . H -> |0>
    flipped.apply_effect(g, gates["X"])     # X . X -> |0>
    assert superposed.function(g, 5, 4) is True
    assert flipped.function(g, 6, 4) is True


def test_roty_never_flips_passability_without_state_change():
    g = Game(argparse.Namespace(level=1))
    pillar = g.objects["5,4"]
    pillar.apply_effect(g, gates["RotY"])  # ~2/3 : 1/3, not pure |0>
    results = [pillar.function(g, 5, 4) for _ in range(25)]
    assert all(r is False for r in results), results  # deterministic, never passable


if __name__ == "__main__":
    test_pure_zero_is_passable()
    test_level2_is_solvable()
    test_roty_never_flips_passability_without_state_change()
    print("walkability checks passed")
