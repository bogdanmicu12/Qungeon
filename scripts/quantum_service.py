"""Host-only Quantum Inspire integration. Credentials stay with the official SDK.

Supports the documented Tuna gate set, with live capacity/topology/status checks.
Never substitutes an emulator for hardware and never retries a submission.
"""

import json
import re
import threading
import time
from pathlib import Path

from scripts.quantum_run import MAX_OPERATIONS, MAX_QUBITS, SHOTS, validate_scene, circuit_diagram

RUN_DIRECTORY = Path(__file__).resolve().parents[1] / ".qungeon-quantum"
TUNA_NAMES = {"Tuna-5": 5, "Tuna-9": 9, "Tuna-17": 17}
MAX_DEPTH = 200
MAX_TWO_QUBIT_GATES = 100


class RunError(Exception):
    def __init__(self, state, message):
        self.state = state
        super().__init__(message)


def make_circuit(payload):
    """Validate a small JSON circuit before passing anything to the SDK."""
    import numpy as np
    from qiskit import QuantumCircuit

    if not isinstance(payload, dict):
        raise ValueError("Invalid circuit.")
    validate_scene(payload.get("scene"))
    labels, operations = payload.get("labels"), payload.get("operations")
    level = payload.get("level")
    if type(level) is not int or not 1 <= level <= 9999:
        raise ValueError("Invalid level.")
    if (not isinstance(labels, list) or not 1 <= len(labels) <= MAX_QUBITS
            or any(not isinstance(s, str) or not re.fullmatch(r"-?\d{1,4},-?\d{1,4}", s) for s in labels)
            or len(set(labels)) != len(labels)):
        raise ValueError(f"Hardware runs support 1 to {MAX_QUBITS} distinct pillars.")
    if not isinstance(operations, list) or len(operations) > MAX_OPERATIONS:
        raise ValueError("Circuit has too many operations.")
    qc = QuantumCircuit(len(labels), len(labels), name=f"Qungeon level {level:02}")
    for op in operations:
        if not isinstance(op, dict):
            raise ValueError("Invalid operation.")
        indices = op.get("qubits")
        if (not isinstance(indices, list) or len(indices) not in (1, 2)
                or any(type(i) is not int or not 0 <= i < len(labels) for i in indices)
                or len(set(indices)) != len(indices)):
            raise ValueError("Unsupported operation or qubit index.")
        parts = np.asarray(op.get("matrix"), dtype=float)
        dim = 2 ** len(indices)
        if parts.shape != (dim, dim, 2) or not np.isfinite(parts).all():
            raise ValueError("Invalid gate matrix.")
        matrix = parts[:, :, 0] + 1j * parts[:, :, 1]
        if not np.allclose(matrix.conj().T @ matrix, np.eye(dim), atol=1e-8, rtol=0):
            raise ValueError("Only unitary gates can run on hardware.")
        # Cirq uses the first operand as the most significant bit; Qiskit uses
        # the last. Reverse operands, preserving controlled gates and phases.
        qc.unitary(matrix, list(reversed(indices)))
    return qc


def eligible_device(info, qubits):
    status = getattr(info.status, "value", info.status)
    return (info.is_hardware is True and info.enabled is True
            and info.name in TUNA_NAMES and info.nqubits == TUNA_NAMES[info.name]
            and qubits <= info.nqubits and status in ("idle", "executing")
            and info.max_number_of_shots > 0)


def compile_circuit(qc, info):
    """Use a conservative documented basis instead of the SDK's broad target.

    The SDK target includes gates that hardware may not support (e.g. Toffoli).
    Routing is based on the live topology, and the entire device is declared.
    """
    from qiskit import QuantumCircuit, transpile
    from qiskit.transpiler import CouplingMap, Target
    from qiskit_quantuminspire import cqasm

    edges = set()
    for edge in info.topology:
        if len(edge) != 2 or any(type(i) is not int or not 0 <= i < info.nqubits for i in edge) or edge[0] == edge[1]:
            raise ValueError("Invalid device topology.")
        edges.add(tuple(edge))
        edges.add(tuple(reversed(edge)))  # CZ is symmetric.
    if not edges:
        raise ValueError("Device connectivity is unavailable.")
    target = Target.from_configuration(
        basis_gates=["rx", "ry", "rz", "cz", "reset", "measure"],
        num_qubits=info.nqubits, coupling_map=CouplingMap(sorted(edges)))
    padded = QuantumCircuit(info.nqubits, qc.num_clbits, name=qc.name)
    padded.reset(range(info.nqubits))
    padded.compose(qc, inplace=True)
    padded.barrier()
    padded.measure(range(qc.num_qubits), range(qc.num_clbits))
    compiled = transpile(padded, target=target, optimization_level=0, seed_transpiler=42)
    two_qubit = sum(len(inst.qubits) == 2 for inst in compiled.data)
    if compiled.depth() > MAX_DEPTH or two_qubit > MAX_TWO_QUBIT_GATES:
        raise ValueError("Circuit is too deep for a useful hardware run.")
    for inst in compiled.data:
        if inst.operation.name == "barrier":
            continue
        indices = tuple(compiled.find_bit(q).index for q in inst.qubits)
        if not target.instruction_supported(inst.operation.name, indices):
            raise ValueError("Compiled circuit exceeds the device gate set or connectivity.")
    cqasm.dumps(compiled)  # Verify serialization before any remote mutation.
    return compiled


def normalize_counts(counts, width):
    """Return bit strings in pillar order, left to right, independent of routing."""
    if not isinstance(counts, dict) or not counts:
        raise ValueError("No measured outcomes were returned.")
    normalized = {}
    for key, count in counts.items():
        bits = str(key).replace(" ", "")
        if not bits or set(bits) - {"0", "1"} or len(bits) > width:
            raise ValueError("Invalid measurement bit string.")
        if type(count) is not int or count < 0:
            raise ValueError("Invalid measurement count.")
        label = bits.zfill(width)[::-1]
        if count:
            normalized[label] = normalized.get(label, 0) + count
    if not normalized:
        raise ValueError("No shots completed.")
    return normalized


class QuantumService:
    def __init__(self, directory=RUN_DIRECTORY, provider_factory=None):
        self.directory = Path(directory)
        self.provider_factory = provider_factory
        self.lock = threading.Lock()
        self.records = {}
        self.jobs = {}
        self.last_poll = {}
        self._credential_stamp = None

    def provider(self):
        if self.provider_factory:
            return self.provider_factory()
        try:
            from qiskit_quantuminspire.qi_provider import QIProvider
        except ImportError as exc:
            raise RunError("setup", "Install the quantum add-on, then connect your Quantum Inspire account.") from exc
        self._refresh_credentials()
        return QIProvider()

    def _refresh_credentials(self):
        from qi2_shared.settings import ApiSettings, API_SETTINGS_FILE
        from qi2_shared.client import connect
        try:
            settings = ApiSettings.from_config_file()
            auth = settings.auths.get(settings.default_host)
            if auth is None or auth.tokens is None or auth.team_member_id is None:
                raise ValueError("Missing authentication")
            stamp = API_SETTINGS_FILE.stat().st_mtime_ns
        except (OSError, ValueError) as exc:
            raise RunError("setup", "Connect your Quantum Inspire account with qi login, then check again.") from exc
        # Re-read credentials after a player runs qi login while the game is open.
        if stamp != self._credential_stamp:
            connect()
            self._credential_stamp = stamp

    def _save(self, key, record):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / (key + ".tmp")
        temporary.write_text(json.dumps(record, allow_nan=False), encoding="utf-8")
        temporary.replace(self.directory / (key + ".json"))

    def _load(self, key):
        if key not in self.records:
            path = self.directory / (key + ".json")
            if path.exists():
                self.records[key] = json.loads(path.read_text(encoding="utf-8"))
        return self.records.get(key)

    @staticmethod
    def public(record):
        result = {k: v for k, v in record.items() if k != "circuit" and (k != "ideal" or record["state"] == "done")}
        # Recover the diagram from the immutable snapshot, including older runs.
        if record.get("labels"):
            result["diagram"] = circuit_diagram(record.get("circuit"))
        return result

    def command(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Invalid request.")
        action, key = payload.get("action"), payload.get("request_id", "")
        if action not in ("prepare", "submit", "status", "history") or not re.fullmatch(r"[0-9a-f]{32}", str(key)):
            raise ValueError("Invalid request.")
        # Serializing actions also protects the SDK's shared token-refresh file.
        with self.lock:
            if action == "history":
                records = []
                for path in sorted(self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
                    try:
                        r = self._load(path.stem)
                        if r.get("state") not in ("ready", "setup", "unavailable"):
                            records.append({k: r[k] for k in ("request_id", "level", "labels", "state", "created", "backend") if k in r})
                    except (OSError, ValueError):
                        continue
                return {"state": "history", "runs": records}
            record = self._load(key)
            if record is None:
                if action != "prepare":
                    return {"state": "unavailable", "message": "This saved run could not be found on this computer."}
                record = {"request_id": key, "circuit": payload.get("circuit"), "state": "idle",
                          "created": time.strftime("%Y-%m-%d %H:%M"), "message": ""}
                self.records[key] = record
            elif action == "prepare" and payload.get("circuit") != record["circuit"]:
                raise ValueError("A run cannot change its circuit.")
            try:
                if action == "prepare" and record["state"] in ("idle", "setup", "unavailable", "ready"):
                    self._prepare(record)
                    self._save(key, record)
                elif action == "submit" and record["state"] == "ready":
                    self._submit(key, record)
                elif action == "status" and record["state"] in ("queued", "running", "submitting", "uncertain"):
                    if time.monotonic() - self.last_poll.get(key, -10) >= 4:
                        self.last_poll[key] = time.monotonic()
                        self._status(key, record)
                        self._save(key, record)
            except RunError as exc:
                if exc.state == "setup" and record["state"] in ("queued", "running", "submitting", "uncertain"):
                    record["message"] = str(exc)
                else:
                    record.update(state=exc.state, message=str(exc))
            except Exception as exc:
                # Do not put provider exceptions, response bodies or credentials
                # into the game, browser, or saved history.
                if record["state"] in ("submitting", "uncertain"):
                    record.update(state="uncertain", message="Submission could not be confirmed. Check My QI before starting another run.")
                elif record["state"] in ("queued", "running"):
                    record["message"] = "Connection interrupted. Your job is saved; status will retry automatically."
                else:
                    status = getattr(exc, "status", None)
                    auth_error = status in (401, 403) or type(exc).__name__ == "AuthorisationError"
                    record.update(state="setup" if auth_error else "unavailable",
                                  message="Account access expired. Run qi login and check again." if auth_error
                                  else "Could not check Quantum Inspire. Check your connection and try again.")
            return self.public(record)

    def _prepare(self, record):
        # Imports stay inside the optional SDK boundary.
        provider = self.provider()
        from qiskit.exceptions import QiskitError
        try:
            qc = make_circuit(record["circuit"])
        except (ValueError, TypeError) as exc:
            raise RunError("unavailable", str(exc)) from exc
        candidates = []
        for backend in provider.backends():
            # Skip unverified families before requesting individual device data.
            if backend.name not in TUNA_NAMES:
                continue
            info = backend.get_backend_type()
            if eligible_device(info, qc.num_qubits):
                candidates.append((info.nqubits, backend, info))
        for _, backend, info in sorted(candidates, key=lambda item: (item[0], item[1].name)):
            try:
                compiled = compile_circuit(qc, info)
            except (ValueError, RuntimeError, QiskitError):
                continue
            record.update(state="ready", backend=backend.name, backend_id=backend.id,
                          shots=min(SHOTS, info.max_number_of_shots), qubits=qc.num_qubits,
                          physical_qubits=info.nqubits, depth=compiled.depth(),
                          level=record["circuit"]["level"], labels=record["circuit"]["labels"],
                          scene=record["circuit"].get("scene"),
                          message="Circuit checked. Ready for a real quantum processor.")
            return
        raise RunError("unavailable", "No compatible Tuna processor is available for this circuit. Devices may be offline, busy calibrating, too small, or require too many gates.")

    def _submit(self, key, record):
        provider = self.provider()
        backend = provider.get_backend(name=record["backend"], id=record["backend_id"])
        info = backend.get_backend_type()
        qc = make_circuit(record["circuit"])
        if not eligible_device(info, qc.num_qubits):
            raise RunError("unavailable", "This processor is no longer available. Check hardware again.")
        compiled = compile_circuit(qc, info)
        from qiskit.quantum_info import Statevector
        ideal = Statevector.from_instruction(qc).probabilities_dict()
        record["ideal"] = {bits[::-1]: float(p) for bits, p in ideal.items() if p > 1e-10}
        record.update(state="submitting", message="Sending your circuit to Quantum Inspire.",
                      shots=min(record["shots"], info.max_number_of_shots))
        # Persist the fence BEFORE making a remote mutation. Even after a crash,
        # repeating this request can never create a second hardware job.
        self._save(key, record)
        try:
            with (self.directory / (key + ".submitted")).open("x", encoding="utf-8") as fence:
                fence.write(record["created"])
        except FileExistsError as exc:
            raise RunError("uncertain", "This run was already submitted. Check status or open My QI.") from exc
        job = backend.run(compiled, shots=record["shots"], memory=False)
        self.jobs[key] = job
        record["job_id"] = str(job.batch_job_id)
        temporary = self.directory / (key + ".qpy.tmp")
        job.serialize(temporary)
        temporary.replace(self.directory / (key + ".qpy"))
        record.update(state="queued", message="Your circuit is in the hardware queue.")
        self._save(key, record)

    def _status(self, key, record):
        if self.provider_factory is None:
            self._refresh_credentials()
        job = self.jobs.get(key)
        if job is None:
            path = self.directory / (key + ".qpy")
            if not path.exists():
                raise RunError("uncertain", "Submission could not be confirmed. Check My QI; this run will not be submitted again.")
            from qiskit_quantuminspire.qi_jobs import QIJob
            job = QIJob.deserialize(self.provider(), path)
            self.jobs[key] = job
        record["job_id"] = str(job.batch_job_id)
        status = job.status().name
        if status in ("ERROR", "CANCELLED"):
            record.update(state="failed", message="Quantum Inspire could not finish this run. See My QI for job details.")
        elif status == "DONE":
            result = job.result(wait_for_results=False)
            if not result.success:
                record.update(state="failed", message="The processor rejected or failed this circuit. See My QI for job details.")
                return
            try:
                counts = normalize_counts(result.get_counts(), record["qubits"])
                actual = sum(counts.values())
                if actual > record["shots"]:
                    raise ValueError("More outcomes than requested shots")
            except ValueError:
                record.update(state="failed", message="The result contained invalid or empty measurement data.")
                return
            record.update(state="done", counts=counts, actual_shots=actual,
                          message="Measurements received." if actual == record["shots"] else "Partial results: fewer shots completed than requested.")
        else:
            record.update(state="running" if status == "RUNNING" else "queued",
                          message="The processor is measuring your circuit." if status == "RUNNING" else "Waiting for the processor. You can keep playing.")


_service = QuantumService()


def default_service():
    return _service
