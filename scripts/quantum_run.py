"""Immutable circuit export and non-blocking UI state, shared with PyScript.

The optional Quantum Inspire SDK is deliberately imported only on the host.
"""

import asyncio
import json
import re
import sys
import time
import uuid

MAX_QUBITS = 17
MAX_OPERATIONS = 512
SHOTS = 1024


def gate_display(operation):
    """Keep Cirq's gate notation alongside the exact matrix used for execution."""
    import cirq

    info = cirq.circuit_diagram_info(operation, default=None)
    symbols = list(info.wire_symbols) if info else ["U"] * len(operation.qubits)
    if info and info.exponent != 1:
        index = info.exponent_qubit_index
        if index is None:
            index = len(symbols) - 1
        symbols[index] += "^" + str(info.exponent)
    if any(len(symbol) > 48 or "\n" in symbol for symbol in symbols):
        symbols = ["U"] * len(operation.qubits)
    name = str(operation.gate)
    if len(name) > 180 or "\n" in name:
        name = "Unitary gate"
    return {"symbols": symbols, "name": name}


def circuit_diagram(circuit):
    """Small, display-only snapshot; execution always uses the gate matrices."""
    if not isinstance(circuit, dict) or "operations" not in circuit:
        return None
    gates = []
    for operation in circuit["operations"]:
        display = operation.get("display", {})
        symbols = display.get("symbols") if isinstance(display, dict) else None
        name = display.get("name") if isinstance(display, dict) else None
        if (not isinstance(symbols, list) or len(symbols) != len(operation["qubits"])
                or any(not isinstance(s, str) or not s or len(s) > 48 or not s.isprintable() for s in symbols)):
            symbols = ["U"] * len(operation["qubits"])
        if not isinstance(name, str) or not name or len(name) > 180 or not name.isprintable():
            name = "Saved unitary gate"
        gates.append({"qubits": list(operation["qubits"]), "symbols": list(symbols), "name": name})
    return {"labels": list(circuit["labels"]), "gates": gates}


def capture_circuit(game):
    """Preserve the actual circuit, including initialization, without measuring it."""
    import cirq
    import numpy as np
    from scripts.game_objects import LootableObject, QuantumObject

    pillars = sorted((obj for obj in game.objects.values() if isinstance(obj, QuantumObject)),
                     key=lambda obj: (obj.position[1], obj.position[0]))
    if not pillars or len(pillars) > MAX_QUBITS:
        raise ValueError(f"Hardware runs support 1 to {MAX_QUBITS} pillars.")
    if game.quantum_grid.post_selection:
        raise ValueError("This circuit uses post-selection, which hardware runs cannot reproduce.")
    indices = {obj.qubit: i for i, obj in enumerate(pillars)}
    operations = []
    for op in game.quantum_grid.circuit.all_operations():
        if not 1 <= len(op.qubits) <= 2 or any(q not in indices for q in op.qubits):
            raise ValueError("This circuit contains an unsupported operation or extra qubit.")
        if not cirq.has_unitary(op):
            raise ValueError("This circuit contains measurements or non-unitary operations.")
        matrix = np.asarray(cirq.unitary(op))
        operations.append({"qubits": [indices[q] for q in op.qubits],
                           "display": gate_display(op),
                           "matrix": [[[float(v.real), float(v.imag)] for v in row] for row in matrix]})
        if len(operations) > MAX_OPERATIONS:
            raise ValueError(f"This circuit exceeds the {MAX_OPERATIONS}-gate hardware limit.")
    scene = {"tiles": {f"{x},{y}": tile.type.name for (x, y), tile in game.tiles.items()},
             "loot": [f"{obj.position[0]},{obj.position[1]}" for obj in game.objects.values() if isinstance(obj, LootableObject)],
             "player": f"{round(game.player.position[0])},{round(game.player.position[1])}"}
    return {"level": game.current_level, "labels": [obj.name for obj in pillars], "operations": operations, "scene": scene}


def validate_scene(scene):
    """Validate optional map metadata; it is never sent to the quantum processor."""
    if scene is None:
        return
    def coordinate(value):
        return isinstance(value, str) and re.fullmatch(r"-?\d{1,4},-?\d{1,4}", value)
    if not isinstance(scene, dict):
        raise ValueError("Invalid pillar map.")
    tiles, loot, player = scene.get("tiles"), scene.get("loot"), scene.get("player")
    if (not isinstance(tiles, dict) or not 1 <= len(tiles) <= 1024
            or any(not coordinate(pos) or kind not in ("EMPTY", "START", "END", "WALL") for pos, kind in tiles.items())
            or not isinstance(loot, list) or len(loot) > 1024
            or any(not coordinate(pos) or pos not in tiles for pos in loot)
            or not coordinate(player) or player not in tiles):
        raise ValueError("Invalid pillar map.")


class QuantumRun:
    """One completed level's run. Polling and SDK calls never block a game frame."""

    def __init__(self, circuit=None, error=None, transport=None):
        self.circuit = circuit
        self.request_id = uuid.uuid4().hex
        self.data = {"state": "unavailable" if error else "idle", "message": error or ""}
        self.busy = False
        self.next_poll = 0
        self.transport = transport
        self._reply = None
        self.started = 0

    def command(self, action):
        if self.busy or self.circuit is None:
            return
        if action == "submit" and self.data["state"] != "ready":
            return
        if action == "enqueue" and self.data["state"] != "idle":
            return
        if action == "retry" and (self.data["state"] not in ("unavailable", "setup") or not self.data.get("retryable")):
            return
        self.busy = True
        self.started = time.monotonic()
        payload = {"action": action, "request_id": self.request_id}
        if action in ("prepare", "enqueue"):
            payload["circuit"] = self.circuit
        if sys.platform == "emscripten" and self.transport is None:
            asyncio.create_task(self._browser_command(payload))
        else:
            import threading
            threading.Thread(target=self._desktop_command, args=(payload,), daemon=True).start()

    def _desktop_command(self, payload):
        try:
            if self.transport is None:
                from scripts.quantum_service import default_service
                self.transport = default_service().command
            self._reply = self.transport(payload)
        except Exception:
            self._reply = {**self.data, "message": "Connection interrupted. Check status before trying again.",
                           "state": "uncertain" if payload["action"] in ("submit", "enqueue", "retry") else self.data["state"]}

    async def _browser_command(self, payload):
        try:
            from pyodide.http import pyfetch
            response = await asyncio.wait_for(pyfetch(
                "/api/quantum", method="POST", headers={"Content-Type": "application/json", "X-Qungeon": "1"},
                body=json.dumps(payload)), timeout=60)
            if response.status == 404 or response.status == 501:
                self._reply = {"state": "setup", "message": "Start the quantum-enabled browser launcher to connect your account."}
            elif not response.ok:
                raise RuntimeError("Quantum service unavailable")
            else:
                self._reply = await response.json()
        except Exception:
            self._reply = {**self.data, "state": "uncertain" if payload["action"] in ("submit", "enqueue", "retry") else self.data["state"],
                           "message": "Connection interrupted. Check status to reconnect to this run."}

    def update(self):
        if self._reply is not None:
            self.data = self._reply
            self._reply = None
            self.busy = False
            self.next_poll = time.monotonic() + 5
        if self.data["state"] in ("queued", "running", "submitting") and time.monotonic() >= self.next_poll:
            self.command("status")

    def open(self):
        if self.data["state"] == "idle":
            self.command("prepare")
