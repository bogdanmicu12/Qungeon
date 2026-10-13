"""Exact local qubit states for the inspector, independent of Pygame.

Only a two-by-two reduced density matrix is needed for each pillar. Never
construct the full density matrix (which would require 4**n entries).
"""

from dataclasses import dataclass

import cirq
import numpy as np


@dataclass(frozen=True)
class BlochState:
    vector: tuple[float, float, float]

    @property
    def probability_zero(self):
        return float(np.clip((1 + self.vector[2]) / 2, 0, 1))

    @property
    def purity(self):
        return float(np.clip((1 + np.dot(self.vector, self.vector)) / 2, 0.5, 1))

    @property
    def description(self):
        if self.purity < 1 - 1e-6:
            return "Mixed local state"
        for vector, name in (
            ((0, 0, 1), "|0>"), ((0, 0, -1), "|1>"),
            ((1, 0, 0), "|+>"), ((-1, 0, 0), "|->"),
            ((0, 1, 0), "|+i>"), ((0, -1, 0), "|-i>"),
        ):
            if np.allclose(self.vector, vector, atol=1e-6, rtol=0):
                return f"Pure state {name}"
        return "Pure superposition"


class BlochStateCache:
    """Simulate once per circuit revision, never on each animation frame.

    The frozen key also catches circuit changes outside the normal gate controls.
    Untouched pillars are |0>; their qubits need not enlarge the simulated register.
    """

    def __init__(self):
        self.clear()

    def clear(self):
        self._key = None
        self._states = {}
        self._error = None

    def read(self, circuit, qubits):
        qubits = tuple(qubits)
        key = (cirq.FrozenCircuit(circuit), qubits)
        if key != self._key:
            self._key = key
            self._states = {}
            self._error = None
            try:
                # Sampling a noisy trajectory would mislabel it as a pure state.
                # Current gameplay is unitary; fail explicitly for other circuits.
                # Circuit.has_unitary may ignore terminal measurements.
                if not all(cirq.has_unitary(op) for op in circuit.all_operations()):
                    raise ValueError("Inspection requires a unitary game circuit.")
                result = cirq.Simulator(dtype=np.complex128).simulate(circuit)
                vector = result.final_state_vector
                for qubit in qubits:
                    if qubit not in result.qubit_map:
                        bloch = (0.0, 0.0, 1.0)
                    else:
                        bloch = tuple(float(v) for v in cirq.bloch_vector_from_state_vector(
                            vector, result.qubit_map[qubit]))
                    self._states[qubit] = BlochState(bloch)
            except (ValueError, TypeError) as error:
                # Cache failures too, instead of retrying an unsupported circuit
                # sixty times a second. A changed circuit is eligible again.
                self._error = str(error)
        if self._error is not None:
            raise ValueError(self._error)
        return self._states
