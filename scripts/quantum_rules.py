"""Quantum rules shared by gameplay and the solver, without UI dependencies."""

import enum
from math import acos, sqrt, pi

import unitary.alpha as alpha
from scripts.flip_phase import FlipPhase
from scripts.swap import SwapEffect


gates = {
    'X': alpha.Flip(),
    'H': alpha.Superposition(),
    'Z': alpha.Phase(),
    'RotY': FlipPhase(-2 * acos(1 / sqrt(3)) / pi),
    'CNOT': None,
    'CHAD': None,
    'SWAP': SwapEffect(),
}
control_gates = ['CNOT', 'CHAD', 'SWAP']
# Walkability uses the exact state vector; this only absorbs float rounding.
PURE_ZERO_TOL = 1e-6


class TileType(enum.Enum):
    EMPTY = 0
    START = 1
    END = 2
    WALL = 4
