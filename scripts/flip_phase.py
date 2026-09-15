from unitary.alpha import QuantumEffect
import cirq
from typing import Optional

class FlipPhase(QuantumEffect):
    """Flips a qubit state with phase change."""
    
    def __init__(self, effect_fraction: float = 1.0):
        self.effect_fraction = effect_fraction

    def num_dimension(self) -> Optional[int]:
        return 2

    def effect(self, *objects):
        for q in objects:
            yield cirq.Y(q.qubit) ** self.effect_fraction

    def __str__(self):
        if self.effect_fraction == 1:
            return "FlipPhase"
        return f"FlipPhase(effect_fraction={self.effect_fraction})"

    def __eq__(self, other):
        if isinstance(other, FlipPhase):
            return self.effect_fraction == other.effect_fraction
        return NotImplemented