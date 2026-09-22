from unitary.alpha import QuantumEffect
import cirq


class SwapEffect(QuantumEffect):
    """A normal two-qubit SWAP gate."""

    def num_dimension(self):
        return 2

    def effect(self, *objects):
        if len(objects) != 2:
            raise ValueError("SWAP gate requires exactly two qubits")

        yield cirq.SWAP(objects[0].qubit, objects[1].qubit)

    def __str__(self):
        return "SWAP"

    def __eq__(self, other):
        return isinstance(other, SwapEffect)