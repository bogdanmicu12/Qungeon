"""Real circuit/SDK checks; fake only the network-facing provider and job calls."""

import json
import os
import threading
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import cirq
import numpy as np
import pygame
import pytest

from Qungeon import Game
from scripts.quantum_run import QuantumRun, capture_circuit


@pytest.fixture
def game():
    result = Game(SimpleNamespace(level=1), settings={}, persist_settings=lambda _: True)
    # Game() no longer loads a level - the quantum stack is imported on demand -
    # so the level these tests run against has to be started explicitly.
    result.start_level(1, "single")
    pygame.event.clear()
    return result


@pytest.fixture
def sdk():
    pytest.importorskip("qiskit_quantuminspire", reason="Install requirements-quantum.txt for hardware integration tests")
    from scripts import quantum_service
    return quantum_service


def device(name="Tuna-5", **changes):
    info = dict(name=name, id=5, description="Test hardware", is_hardware=True, enabled=True,
                status="idle", nqubits=5, max_number_of_shots=2048, default_number_of_shots=1024,
                topology=[[0, 2], [1, 2], [2, 3], [2, 4]], supports_raw_data=False)
    info.update(changes)
    return SimpleNamespace(**info)


def network_fixture(info=None):
    from qiskit_quantuminspire.qi_backend import QIBackend
    from qiskit_quantuminspire.qi_jobs import QIJob
    from qiskit.providers import JobStatus

    class Backend(QIBackend):
        def __init__(self):
            self.info = info or device()
            super().__init__(self.info)
            self.submitted = []

        def get_backend_type(self):
            return self.info

        def run(self, circuit, **options):
            self.submitted.append((circuit, options))
            job = QIJob(circuit, self)
            job.batch_job_id = 123
            job.circuits_run_data[0].job_id = 456
            job.status = lambda: JobStatus.QUEUED
            return job

    backend = Backend()
    provider = SimpleNamespace(backends=lambda: [backend], get_backend=lambda *a, **kw: backend)
    return backend, provider


@pytest.mark.parametrize("level", range(1, 9))
def test_every_level_exports_same_state_in_pillar_order(game, sdk, level):
    from qiskit.quantum_info import Statevector
    game.start_level(level)
    before = game.quantum_grid.circuit.copy()
    payload = capture_circuit(game)
    qc = sdk.make_circuit(payload)
    qubits = [game.objects[label].qubit for label in payload["labels"]]
    original = cirq.Simulator(dtype=np.complex128).simulate(before, qubit_order=qubits).final_state_vector
    converted = Statevector.from_instruction(qc).reverse_qargs().data
    np.testing.assert_allclose(abs(original)**2, abs(converted)**2, atol=1e-8)
    assert cirq.linalg.allclose_up_to_global_phase(original, converted, atol=1e-8)
    assert before == game.quantum_grid.circuit


def test_controlled_gates_fractional_rotation_and_unused_pillars(game, sdk):
    from qiskit.quantum_info import Statevector
    game.start_level(8)
    pillars = sorted([obj for obj in game.objects.values() if hasattr(obj, "qubit")], key=lambda obj: (obj.position[1], obj.position[0]))
    a, b, c = [obj.qubit for obj in pillars]
    game.quantum_grid.circuit = cirq.Circuit(cirq.X(b), cirq.Y(a)**-0.608, cirq.H(b).controlled_by(a), cirq.CNOT(b, a), cirq.Z(a))
    payload = capture_circuit(game)
    qc = sdk.make_circuit(payload)
    actual = Statevector.from_instruction(qc).reverse_qargs().data
    expected = cirq.Simulator(dtype=np.complex128).simulate(game.quantum_grid.circuit, qubit_order=[a, b, c]).final_state_vector
    assert cirq.linalg.allclose_up_to_global_phase(expected, actual, atol=1e-8)


def test_snapshot_is_immutable_and_measurements_are_rejected(game):
    snapshot = capture_circuit(game)
    game.objects["5,4"].apply_effect(game, __import__("unitary.alpha", fromlist=["Flip"]).Flip())
    assert snapshot != capture_circuit(game)
    qubit = next(iter(game.quantum_grid.circuit.all_qubits()))
    game.quantum_grid.circuit.append(cirq.measure(qubit))
    with pytest.raises(ValueError, match="measurements"):
        capture_circuit(game)


@pytest.mark.parametrize("change", [{"is_hardware": False}, {"enabled": False}, {"status": "offline"},
                                    {"status": "calibrating"}, {"nqubits": 4}, {"max_number_of_shots": 0},
                                    {"name": "QX emulator"}])
def test_hardware_filter_fails_closed(sdk, change):
    assert not sdk.eligible_device(device(**change), 2)
    assert not sdk.eligible_device(device(), 6)


def test_routing_cqasm_and_measurement_mapping(sdk):
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector
    from qiskit_quantuminspire import cqasm
    qc = QuantumCircuit(3, 3)
    qc.x(0)
    qc.h(1)
    qc.cx(1, 2)
    compiled = sdk.compile_circuit(qc, device())
    assert compiled.num_qubits == 5
    program = cqasm.dumps(compiled)
    assert "version 3.0" in program and "qubit[5]" in program
    assert set(compiled.count_ops()) <= {"rx", "ry", "rz", "cz", "reset", "measure", "barrier"}
    edges = {frozenset(edge) for edge in device().topology}
    for inst in compiled.data:
        if inst.operation.name == "cz":
            assert frozenset(compiled.find_bit(q).index for q in inst.qubits) in edges
    final = compiled.remove_final_measurements(inplace=False)
    probabilities = Statevector.from_instruction(final).probabilities_dict()
    mapping = {compiled.find_bit(inst.clbits[0]).index: compiled.find_bit(inst.qubits[0]).index
               for inst in compiled.data if inst.operation.name == "measure"}
    observed = {}
    for bits, probability in probabilities.items():
        outcome = "".join(bits[::-1][mapping[i]] for i in range(3))
        observed[outcome] = observed.get(outcome, 0) + probability
    assert observed["100"] == pytest.approx(0.5)
    assert observed["111"] == pytest.approx(0.5)


def test_depth_guard(sdk):
    from qiskit import QuantumCircuit
    qc = QuantumCircuit(2, 2)
    for _ in range(101):
        qc.cz(0, 1)
    with pytest.raises(ValueError, match="too deep"):
        sdk.compile_circuit(qc, device())


@pytest.mark.parametrize("mutate", [lambda p: p.update(level=True), lambda p: p.update(labels=["../secrets"]),
                                    lambda p: p["operations"][0].update(qubits=[999]),
                                    lambda p: p["operations"][0].update(matrix=[[[float("nan"), 0]]]),
                                    lambda p: p["operations"][0].update(matrix=[[[0, 0], [0, 0]], [[0, 0], [0, 0]]])])
def test_untrusted_circuit_validation(game, sdk, mutate):
    payload = capture_circuit(game)
    mutate(payload)
    with pytest.raises((ValueError, TypeError)):
        sdk.make_circuit(payload)


def test_submit_is_idempotent_and_results_recover_from_disk(game, sdk, tmp_path, monkeypatch):
    from qiskit.providers import JobStatus
    from qiskit_quantuminspire.qi_jobs import QIJob
    backend, provider = network_fixture(device(max_number_of_shots=512))
    service = sdk.QuantumService(tmp_path, lambda: provider)
    key = "a" * 32
    command = {"request_id": key, "action": "prepare", "circuit": capture_circuit(game)}
    assert service.command(command)["shots"] == 512
    command["action"] = "submit"
    assert service.command(command)["state"] == "queued"
    assert service.command(command)["state"] == "queued"
    assert len(backend.submitted) == 1
    assert (tmp_path / (key + ".qpy")).is_file()
    # Recovery exercises the SDK's actual QPY deserializer, with network calls stubbed.
    monkeypatch.setattr(QIJob, "status", lambda self: JobStatus.DONE)
    monkeypatch.setattr(QIJob, "result", lambda *a, **kw: SimpleNamespace(success=True, get_counts=lambda: {"0": 500, "1": 12}))
    recovered = sdk.QuantumService(tmp_path, lambda: provider)
    result = recovered.command({"request_id": key, "action": "status"})
    assert result["state"] == "done"
    assert result["actual_shots"] == 512
    assert result["counts"] == {"0": 500, "1": 12}
    assert result["scene"] == command["circuit"]["scene"]
    from scripts.quantum_run import circuit_diagram
    assert result["diagram"] == circuit_diagram(command["circuit"])
    assert result["job_id"] == "123"
    history = recovered.command({"request_id": key, "action": "history"})
    assert history["runs"][0]["request_id"] == key


def test_ambiguous_submission_never_retries_after_restart(game, sdk, tmp_path):
    backend, provider = network_fixture()
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("secret token must not appear")
    backend.run = interrupted
    key = "b" * 32
    service = sdk.QuantumService(tmp_path, lambda: provider)
    service.command({"action": "prepare", "request_id": key, "circuit": capture_circuit(game)})
    result = service.command({"action": "submit", "request_id": key})
    assert result["state"] == "uncertain"
    assert "secret" not in json.dumps(result)
    recovered = sdk.QuantumService(tmp_path, lambda: provider)
    recovered.command({"action": "submit", "request_id": key})
    recovered.command({"action": "prepare", "request_id": key, "circuit": capture_circuit(game)})
    assert len(calls) == 1


def test_device_goes_offline_between_prepare_and_submit(game, sdk, tmp_path):
    backend, provider = network_fixture()
    service = sdk.QuantumService(tmp_path, lambda: provider)
    key = "c" * 32
    service.command({"action": "prepare", "request_id": key, "circuit": capture_circuit(game)})
    backend.info.status = "offline"
    assert service.command({"action": "submit", "request_id": key})["state"] == "unavailable"
    assert not backend.submitted


@pytest.mark.parametrize("success,counts,expected", [(False, {}, "failed"), (True, {}, "failed"),
                                                     (True, {"0": 100}, "done"), (True, {"0": 2000}, "failed")])
def test_failed_empty_partial_and_invalid_job_results(game, sdk, tmp_path, success, counts, expected):
    from qiskit.providers import JobStatus
    backend, provider = network_fixture()
    service = sdk.QuantumService(tmp_path, lambda: provider)
    key = "d" * 32
    service.command({"action": "prepare", "request_id": key, "circuit": capture_circuit(game)})
    service.command({"action": "submit", "request_id": key})
    job = service.jobs[key]
    job.status = lambda: JobStatus.DONE
    job.result = lambda **kw: SimpleNamespace(success=success, get_counts=lambda: counts)
    result = service.command({"action": "status", "request_id": key})
    assert result["state"] == expected
    if expected == "done":
        assert result["actual_shots"] == 100
        assert "Partial" in result["message"]


def test_polling_failure_preserves_job_for_recovery(game, sdk, tmp_path):
    from qiskit.providers import JobStatus
    backend, provider = network_fixture()
    service = sdk.QuantumService(tmp_path, lambda: provider)
    key = "e" * 32
    service.command({"action": "prepare", "request_id": key, "circuit": capture_circuit(game)})
    service.command({"action": "submit", "request_id": key})
    job = service.jobs[key]
    def interrupted():
        raise ConnectionError("private account detail")
    job.status = interrupted
    result = service.command({"action": "status", "request_id": key})
    assert result["state"] == "queued" and result["job_id"] == "123"
    assert "private" not in json.dumps(result)
    job.status = lambda: JobStatus.RUNNING
    service.last_poll.clear()
    assert service.command({"action": "status", "request_id": key})["state"] == "running"
    assert len(backend.submitted) == 1


def test_reauthentication_never_turns_pending_job_into_new_submission(game, sdk, tmp_path, monkeypatch):
    backend, provider = network_fixture()
    service = sdk.QuantumService(tmp_path, lambda: provider)
    key = "2" * 32
    service.command({"action": "prepare", "request_id": key, "circuit": capture_circuit(game)})
    service.command({"action": "submit", "request_id": key})
    def expired(*args):
        raise sdk.RunError("setup", "Run qi login to renew access.")
    monkeypatch.setattr(service, "_status", expired)
    result = service.command({"action": "status", "request_id": key})
    assert result["state"] == "queued"
    assert "qi login" in result["message"]
    service.command({"action": "submit", "request_id": key})
    assert len(backend.submitted) == 1


def test_missing_account_is_actionable_without_network(game, sdk, tmp_path, monkeypatch):
    from qi2_shared.settings import ApiSettings
    def missing(*a, **kw):
        raise FileNotFoundError()
    monkeypatch.setattr(ApiSettings, "from_config_file", missing)
    service = sdk.QuantumService(tmp_path)
    result = service.command({"action": "prepare", "request_id": "f" * 32, "circuit": capture_circuit(game)})
    assert result["state"] == "setup"
    assert "qi login" in result["message"]


def test_second_process_cannot_resubmit_stale_ready_record(game, sdk, tmp_path):
    backend, provider = network_fixture()
    key = "1" * 32
    first = sdk.QuantumService(tmp_path, lambda: provider)
    first.command({"action": "prepare", "request_id": key, "circuit": capture_circuit(game)})
    second = sdk.QuantumService(tmp_path, lambda: provider)
    second._load(key)  # This process holds a stale "ready" record.
    first.command({"action": "submit", "request_id": key})
    assert second.command({"action": "submit", "request_id": key})["state"] == "uncertain"
    assert len(backend.submitted) == 1


@pytest.mark.parametrize("counts", [{}, {"0": 0}, {"02": 5}, {"00": -1}, {"00": 1.5}, {"100": 1}])
def test_reject_bad_results(sdk, counts):
    with pytest.raises(ValueError):
        sdk.normalize_counts(counts, 2)


def test_result_endianness(sdk):
    assert sdk.normalize_counts({"01": 10, "10": 20}, 2) == {"10": 10, "01": 20}


def test_controller_keeps_game_responsive_and_blocks_double_clicks():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def transport(payload):
        calls.append(payload)
        entered.set()
        release.wait(2)
        return {"state": "queued"}
    run = QuantumRun({"level": 1}, transport=transport)
    run.data = {"state": "ready"}
    run.command("submit")
    assert entered.wait(1)
    run.command("submit")
    assert run.busy and len(calls) == 1
    release.set()


def test_completion_button_keyboard_and_results_scrolling(game):
    game.start_level(1)
    game.advance_level()
    run = game.quantum_run
    run.data = {"state": "ready", "shots": 1024, "backend": "Tuna-5", "depth": 4}
    button = next(b for b in game.menu.buttons() if b[0] == "quantum_run")
    assert button[2] == "Run on Quantum Computer"
    game.menu.activate(button[0])
    assert game.menu.page == "quantum"
    game.menu.focus = 99
    run.data = {"state": "done", "backend": "Tuna-5", "shots": 1024, "actual_shots": 1024,
                "counts": {format(i, "03b"): 128 for i in range(8)}, "ideal": {}, "labels": ["0,0", "1,0", "2,0"]}
    game.menu.draw()
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-2, pos=(400, 350), mod=0))
    assert game.menu.quantum.result_scroll.y == 72
    game.menu.activate("quantum:map")
    game.menu.draw()
    game.menu.back()
    assert game.menu.page == "quantum"
    game.menu.back()
    assert game.menu.page == "complete"
    assert game.quantum_run is run


def test_pillar_map_renders_saved_level_and_selects_matching_result_bit(game):
    from scripts.pillar_map import PillarMap
    game.start_level(8)
    game.advance_level()
    run = game.quantum_run
    scene = run.circuit["scene"]
    run.data = {"state": "done", "level": 8, "labels": run.circuit["labels"], "scene": scene,
                "actual_shots": 1024, "counts": {"100": 512, "010": 256, "111": 256},
                "ideal": {"000": .5, "111": .5}}
    game.menu.quantum.run = run
    game.start_level(1)  # The map must not start showing the currently played level.
    game.menu.activate("quantum:map")
    view = game.menu.quantum.pillar_map
    assert view.labels == ["4,3", "5,3", "6,3"]
    assert view.scene == scene
    assert view.tiles[(7, 3)] == "END"
    assert len(view.rects) == 3
    assert all(PillarMap.VIEW.contains(rect) for rect in view.rects)
    assert view.probabilities() == [(.75, .5), (.5, .5), (.25, .5)]
    # Hit an actual pillar sprite, then navigate to the next one with the keyboard.
    pos = view.rects[1].center
    for kind in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        game.menu.handle_event(pygame.event.Event(kind, button=1, pos=pos))
    game.menu.draw()
    assert view.selected == 1
    game.menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, mod=0))
    game.menu.draw()
    assert view.selected == 2


@pytest.mark.parametrize("level", range(1, 9))
def test_every_shipped_map_fits_and_keeps_all_pillars_visible(game, level):
    from scripts.pillar_map import PillarMap
    game.start_level(level)
    game.advance_level()
    game.menu.quantum.run = game.quantum_run
    game.menu.activate("quantum:map")
    view = game.menu.quantum.pillar_map
    assert len(view.rects) == len(game.quantum_run.circuit["labels"])
    assert all(PillarMap.VIEW.contains(rect.inflate(4, 4)) for rect in view.rects)
    game.menu.draw()


def test_older_run_map_falls_back_to_pillar_positions_when_level_is_missing(game):
    from scripts.pillar_map import PillarMap
    run = QuantumRun({"level": 9999, "labels": ["2,3", "4,5"]})
    view = PillarMap(game.menu, run)
    assert view.caption == "SAVED PILLAR POSITIONS"
    assert len(view.rects) == 2
    assert view.probabilities() == [(None, None), (None, None)]


def test_results_links_are_adjacent_and_pillar_map_stays_at_far_right(game):
    game.advance_level()
    run = game.quantum_run
    run.data = {"state": "done", "counts": {format(i, "04b"): 1 for i in range(16)}}
    game.menu.quantum.run = run
    game.menu.open("quantum")
    buttons = game.menu.buttons()
    rects = [rect for _, rect, _, _ in buttons]
    mapping = {action: rect for action, rect, _, _ in buttons}
    assert mapping["quantum:map"].right == 740
    assert mapping["quantum:circuit"].y == mapping["quantum:map"].y
    assert mapping["quantum:circuit"].right + 16 == mapping["quantum:map"].left
    assert not any("results:" in action for action in mapping)
    assert not any(a.colliderect(b) for i, a in enumerate(rects) for b in rects[i+1:])


def test_map_metadata_is_validated_before_hardware_submission(game, sdk):
    payload = capture_circuit(game)
    payload["scene"]["tiles"]["0,0"] = "unknown-asset"
    with pytest.raises(ValueError, match="pillar map"):
        sdk.make_circuit(payload)


def test_circuit_notation_preserves_control_order_and_fractional_power(game):
    from scripts.quantum_run import circuit_diagram
    game.start_level(8)
    a, b, c = [game.objects[label].qubit for label in capture_circuit(game)["labels"]]
    game.quantum_grid.circuit = cirq.Circuit(cirq.Y(a)**-0.608, cirq.CNOT(c, a),
                                           cirq.H(b).controlled_by(a), cirq.X(b))
    diagram = circuit_diagram(capture_circuit(game))
    assert {"qubits": [0], "symbols": ["Y^-0.608"], "name": "Y**-0.608"} in diagram["gates"]
    assert {"qubits": [2, 0], "symbols": ["@", "X"], "name": "CNOT"} in diagram["gates"]
    assert {"qubits": [0, 1], "symbols": ["@", "H"], "name": "CH"} in diagram["gates"]


def test_circuit_only_opens_from_results_and_has_only_back_button(game):
    game.advance_level()
    run = game.quantum_run
    calls = []
    run.transport = lambda payload: calls.append(payload)
    before = game.quantum_grid.circuit.copy()
    assert not any("circuit" in action for action, *_ in game.menu.buttons())
    game.menu.activate("quantum_circuit")
    assert game.menu.page == "complete"
    game.menu.quantum.run = run
    game.menu.open("quantum")
    for state in ("idle", "ready", "queued", "failed", "unavailable", "setup"):
        run.data = {"state": state, "shots": 1024}
        assert "quantum:circuit" not in [b[0] for b in game.menu.buttons()]
        game.menu.activate("quantum:circuit")
        assert game.menu.page == "quantum"
    run.data = {"state": "done"}
    game.menu.activate("quantum:circuit")
    assert game.menu.page == "quantum_circuit"
    assert [b[0] for b in game.menu.buttons()] == ["back"]
    view = game.menu.quantum.circuit_view
    # Gate details remain selectable without adding navigation buttons.
    pos = view.gate_rect(0).center
    for kind in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        game.menu.handle_event(pygame.event.Event(kind, button=1, pos=pos))
    game.menu.draw()
    assert view.selected == 0
    game.menu.back()
    assert game.menu.page == "quantum"
    assert not calls and not run.busy
    assert game.quantum_grid.circuit == before


def test_circuit_scrolls_both_axes_and_selects_readout_after_scrolling(game):
    game.start_level(6)
    pillars = [game.objects[label].qubit for label in capture_circuit(game)["labels"]]
    game.quantum_grid.circuit = cirq.Circuit([cirq.H(pillars[0])] * 13 + [cirq.CNOT(pillars[-1], pillars[0])])
    game.advance_level()
    game.menu.quantum.run = game.quantum_run
    game.quantum_run.data = {"state": "done"}
    game.menu.open("quantum")
    game.menu.activate("quantum:circuit")
    view = game.menu.quantum.circuit_view
    wheel = dict(x=0, y=-1, pos=view.VIEW.center, mod=0)
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, **wheel, precise_y=-0.25))
    assert view.scroll.y == 9 and view.scroll.x == 0
    wheel["mod"] = pygame.KMOD_SHIFT
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, **wheel))
    assert view.scroll.x == 36 and view.scroll.y == 9
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=1, y=0, pos=view.VIEW.center, mod=0))
    assert view.scroll.x == 72
    game.menu.draw()
    game.menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_END))
    assert view.scroll.x == view.scroll.max_x and view.scroll.y == view.scroll.max_y
    rect = view.gate_rect(view.total - 1)
    assert view.VIEW.contains(rect)
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        game.menu.handle_event(pygame.event.Event(kind, button=1, pos=rect.center))
    assert view.selected == view.total - 1
    game.menu.draw()
    game.menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_HOME))
    assert view.scroll.x == view.scroll.y == 0


def test_saved_circuit_view_survives_changing_levels(game, sdk):
    game.start_level(8)
    circuit = capture_circuit(game)
    data = sdk.QuantumService().public({"state": "done", "labels": circuit["labels"], "circuit": circuit})
    # A recovered browser run only receives the display snapshot, not matrices.
    assert "circuit" not in data
    game.start_level(1)
    run = QuantumRun({"level": 8, "labels": circuit["labels"]})
    run.data = data
    game.menu.quantum.run = run
    game.menu.open("quantum")
    game.menu.activate("quantum:circuit")
    view = game.menu.quantum.circuit_view
    assert view.labels == circuit["labels"]
    assert len(view.gates) == len(circuit["operations"])
    game.menu.draw()
    game.menu.back()
    assert game.menu.page == "quantum"


def test_empty_and_legacy_circuits_have_an_honest_readable_view(game):
    from scripts.quantum_run import circuit_diagram
    circuit = capture_circuit(game)
    for operation in circuit["operations"]:
        operation.pop("display")
    assert all(g["symbols"] == ["U"] for g in circuit_diagram(circuit)["gates"])
    circuit["operations"] = []
    game.quantum_run = QuantumRun(circuit)
    game.quantum_run.data = {"state": "done"}
    game.menu.quantum.run = game.quantum_run
    game.menu.open("quantum")
    game.menu.activate("quantum:circuit")
    assert game.menu.quantum.circuit_view.total == 1
    game.menu.draw()
    assert game.menu.quantum.circuit_view.scroll.bars() == []


def test_results_scrollbar_reaches_last_outcome_and_preserves_position_on_back(game):
    game.advance_level()
    run = game.quantum_run
    run.data = {"state": "done", "backend": "TEST", "shots": 64, "actual_shots": 64,
                "counts": {format(i, "06b"): 1 for i in range(64)}}
    game.menu.quantum.run = run
    game.menu.open("quantum")
    game.menu.draw()
    scroll = game.menu.quantum.result_scroll
    _, track, thumb = scroll.bars()[0]
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=thumb.center))
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(track.centerx, track.bottom+100)))
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(track.centerx, track.bottom+100)))
    assert scroll.y == scroll.max_y and scroll.drag is None
    drawn = []
    original = game.menu.text
    def record(value, *args, **kwargs):
        drawn.append(value)
        original(value, *args, **kwargs)
    game.menu.text = record
    game.menu.draw()
    assert "111111" in drawn and "000000" not in drawn
    game.menu.activate("quantum:circuit")
    game.menu.back()
    assert scroll.y == scroll.max_y
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=999, pos=(400, 350), mod=0))
    assert scroll.y == 0


def test_refresh_on_right_and_home_buttons_align(game):
    game.menu.open("main")
    home = {action: rect for action, rect, *_ in game.menu.buttons()}
    assert home["quantum_history"].y == home["help"].y
    assert home["quantum_history"].height == home["help"].height
    history = QuantumRun({})
    history.data = {"runs": [{"request_id": f"{i:032x}", "level": 1, "state": "done"} for i in range(12)]}
    game.menu.quantum.history = history
    game.menu.open("quantum_history")
    buttons = {action: rect for action, rect, *_ in game.menu.buttons()}
    assert buttons["quantum:refresh_history"].right == 740
    rects = [game.menu.button_hit_rect(action, rect) for action, rect in buttons.items()]
    assert not any(a.colliderect(b) for i, a in enumerate(rects) for b in rects[i+1:])


def test_horizontal_wheel_fallback_and_drag_cancellation(game):
    game.advance_level()
    circuit = game.quantum_run.circuit
    circuit["operations"] *= 30  # One pillar; only the horizontal axis overflows.
    game.quantum_run.data = {"state": "done"}
    game.menu.quantum.run = game.quantum_run
    game.menu.open("quantum")
    game.menu.activate("quantum:circuit")
    scroll = game.menu.quantum.circuit_view.scroll
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1, pos=(400, 350), mod=0))
    assert scroll.x == 36 and scroll.y == 0
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1, pos=(400, 550), mod=0))
    assert scroll.x == 36  # Wheel input outside the panel leaves it alone.
    _, track, thumb = scroll.bars()[0]
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=thumb.center))
    game.menu.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(track.right+50, track.centery)))
    assert scroll.x == scroll.max_x
    game.menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert game.menu.page == "quantum" and scroll.drag is None


def test_automatic_enqueue_prepares_and_submits_once_across_restarts(game, sdk, tmp_path):
    backend, provider = network_fixture()
    payload = {"action": "enqueue", "request_id": "3" * 32, "circuit": capture_circuit(game)}
    service = sdk.QuantumService(tmp_path, lambda: provider)
    result = service.command(payload)
    assert result["state"] == "queued" and result["automatic"] is True
    assert result["shots"] == 1024
    assert len(backend.submitted) == 1
    service.command(payload)
    recovered = sdk.QuantumService(tmp_path, lambda: provider)
    assert recovered.command(payload)["state"] == "queued"
    assert len(backend.submitted) == 1
    assert recovered.command({"action": "history", "request_id": "3" * 32})["runs"][0]["level"] == 1


@pytest.mark.parametrize("state", ["setup", "unavailable"])
def test_automatic_unavailable_runs_are_saved_without_submitting(game, sdk, tmp_path, state):
    backend, provider = network_fixture(device(status="offline"))
    def missing():
        raise sdk.RunError("setup", "Connect your account with qi login.")
    service = sdk.QuantumService(tmp_path, missing if state == "setup" else lambda: provider)
    payload = {"action": "enqueue", "request_id": "4" * 32, "circuit": capture_circuit(game)}
    result = service.command(payload)
    assert result["state"] == state
    recovered = sdk.QuantumService(tmp_path, lambda: provider)
    rows = recovered.command({"action": "history", "request_id": "4" * 32})["runs"]
    assert rows[0]["level"] == 1 and rows[0]["state"] == state
    backend.info.status = "idle"
    # A failed automatic attempt is not silently replayed after reconnection.
    assert recovered.command(payload)["state"] == state
    assert not backend.submitted
    game.menu.quantum.run = QuantumRun({"level": 1, "labels": result["labels"]})
    game.menu.quantum.run.data = result
    game.menu.open("quantum")
    assert "quantum:prepare" not in [b[0] for b in game.menu.buttons()]
    game.menu.draw()


def test_automatic_uncertain_submission_is_never_repeated(game, sdk, tmp_path):
    backend, provider = network_fixture()
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("private account detail")
    backend.run = interrupted
    payload = {"action": "enqueue", "request_id": "5" * 32, "circuit": capture_circuit(game)}
    service = sdk.QuantumService(tmp_path, lambda: provider)
    assert service.command(payload)["state"] == "uncertain"
    result = sdk.QuantumService(tmp_path, lambda: provider).command(payload)
    assert result["state"] == "uncertain" and len(calls) == 1
    assert "private account detail" not in json.dumps(result)


def test_automatic_controller_disconnect_keeps_submission_uncertain(game):
    def disconnected(payload):
        assert payload["action"] == "enqueue" and payload["circuit"]["level"] == 1
        raise ConnectionError("Connection lost")
    run = QuantumRun(capture_circuit(game), transport=disconnected)
    run._desktop_command({"action": "enqueue", "circuit": run.circuit})
    run.update()
    assert run.data["state"] == "uncertain"
    run.command("enqueue")
    assert not run.busy


@pytest.mark.parametrize("legacy", [False, True])
def test_retry_saved_unavailable_circuit_once_after_restart(game, sdk, tmp_path, legacy):
    backend, provider = network_fixture(device(status="offline", max_number_of_shots=512))
    service = sdk.QuantumService(tmp_path, lambda: provider)
    key = "6" * 32
    original = capture_circuit(game)
    result = service.command({"action": "enqueue", "request_id": key, "circuit": original})
    assert result["state"] == "unavailable" and result["retryable"]
    if legacy:
        record = service.records[key]
        record.pop("retryable")
        service._save(key, record)
    stale = sdk.QuantumService(tmp_path, lambda: provider)
    stale._load(key)
    recovered = sdk.QuantumService(tmp_path, lambda: provider)
    retry = {"action": "retry", "request_id": key}
    # Still offline: the same attempt stays actionable and sends nothing.
    result = recovered.command(retry)
    assert result["state"] == "unavailable" and result["retryable"]
    assert not backend.submitted
    backend.info.status = "idle"
    game.start_level(2)
    # Retry ignores replacement circuits; it uses the original host snapshot.
    result = recovered.command({**retry, "circuit": capture_circuit(game)})
    assert result["state"] == "queued" and result["retryable"] is False
    assert result["level"] == 1 and result["shots"] == 512
    assert recovered.records[key]["circuit"] == original
    assert "circuit" not in result
    assert recovered.command(retry)["state"] == "queued"
    assert stale.command(retry)["state"] == "queued"
    assert sdk.QuantumService(tmp_path, lambda: provider).command(retry)["state"] == "queued"
    assert len(backend.submitted) == 1
    assert backend.submitted[0][1]["shots"] == 512
    rows = recovered.command({"action": "history", "request_id": key})["runs"]
    assert len(rows) == 1 and rows[0]["state"] == "queued"


@pytest.mark.parametrize("failure", ["connection", "account"])
def test_retry_can_recover_from_pre_submission_connection_or_account_failure(game, sdk, tmp_path, failure):
    backend, provider = network_fixture(device(status="offline"))
    service = sdk.QuantumService(tmp_path, lambda: provider)
    key = "7" * 32
    service.command({"action": "enqueue", "request_id": key, "circuit": capture_circuit(game)})
    def interrupted():
        if failure == "account":
            raise sdk.RunError("setup", "Run qi login to reconnect your account.")
        raise ConnectionError("private account details")
    service.provider_factory = interrupted
    result = service.command({"action": "retry", "request_id": key})
    assert result["state"] == ("setup" if failure == "account" else "unavailable")
    assert result["retryable"] and "private" not in json.dumps(result)
    assert not backend.submitted
    backend.info.status = "idle"
    service.provider_factory = lambda: provider
    assert service.command({"action": "retry", "request_id": key})["state"] == "queued"
    assert len(backend.submitted) == 1


def test_ambiguous_retry_cannot_submit_again(game, sdk, tmp_path):
    backend, provider = network_fixture(device(status="offline"))
    service = sdk.QuantumService(tmp_path, lambda: provider)
    key = "8" * 32
    service.command({"action": "enqueue", "request_id": key, "circuit": capture_circuit(game)})
    backend.info.status = "idle"
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("private account details")
    backend.run = interrupted
    retry = {"action": "retry", "request_id": key}
    result = service.command(retry)
    assert result["state"] == "uncertain" and result["retryable"] is False
    assert "private" not in json.dumps(result)
    result = sdk.QuantumService(tmp_path, lambda: provider).command(retry)
    assert result["state"] == "uncertain" and len(calls) == 1


@pytest.mark.parametrize("guard", ["invalid", "failed", "fence", "job_id"])
def test_retry_does_not_replay_invalid_or_already_submitted_runs(game, sdk, tmp_path, guard):
    backend, provider = network_fixture(device(status="offline"))
    service = sdk.QuantumService(tmp_path, lambda: provider)
    key = "9" * 32
    circuit = capture_circuit(game)
    if guard == "invalid":
        circuit["operations"][0]["qubits"] = [999]
    service.command({"action": "enqueue", "request_id": key, "circuit": circuit})
    if guard == "failed":
        service.records[key]["state"] = "failed"
    elif guard == "job_id":
        service.records[key]["job_id"] = "already-submitted"
    elif guard == "fence":
        (tmp_path / (key + ".submitted")).touch()
    service._save(key, service.records[key])
    backend.info.status = "idle"
    result = service.command({"action": "retry", "request_id": key})
    assert result["retryable"] is False and not backend.submitted
    assert result["state"] == ("failed" if guard == "failed" else "unavailable")


def test_retry_saved_run_button_is_responsive_and_guards_double_clicks(game):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []
    run = QuantumRun({"level": 1, "labels": ["1,1"]})
    def transport(payload):
        calls.append(payload)
        entered.set()
        release.wait(2)
        finished.set()
        return {"state": "queued", "backend": "Test hardware"}
    run.transport = transport
    run.data = {"state": "unavailable", "retryable": True, "message": "Hardware unavailable."}
    game.menu.quantum.run = run
    game.menu.open("quantum")
    assert [(b[0], b[2]) for b in game.menu.buttons()] == [("back", "Back"), ("quantum:retry", "Retry")]
    game.menu.draw()
    try:
        game.menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
        game.menu.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        assert entered.wait(1) and run.busy
        assert [b[0] for b in game.menu.buttons()] == ["back"]
        game.menu.activate("quantum:retry")
        assert calls == [{"action": "retry", "request_id": run.request_id}]
        game.menu.draw()
    finally:
        release.set()
        assert finished.wait(1)


def test_return_to_hardware_history_refreshes_retried_status(game):
    loaded = threading.Event()
    def history(payload):
        assert payload["action"] == "history"
        loaded.set()
        return {"state": "history", "runs": []}
    menu = game.menu.quantum
    menu.history = QuantumRun({}, transport=history)
    menu.run = QuantumRun({"level": 1, "labels": ["1,1"]})
    menu.run.data = {"state": "queued"}
    menu.return_page = "quantum_history"
    game.menu.open("quantum")
    game.menu.back()
    assert game.menu.page == "quantum_history" and loaded.wait(1)


@pytest.mark.parametrize("browser", [False, True])
def test_retry_controller_disconnect_requires_status_before_retrying(game, monkeypatch, browser):
    import asyncio
    import sys
    run = QuantumRun({"level": 1, "labels": ["1,1"]})
    run.data = {"state": "unavailable", "retryable": True}
    payload = {"action": "retry", "request_id": run.request_id}
    def disconnected(*args, **kwargs):
        raise ConnectionError("Connection lost")
    if browser:
        monkeypatch.setitem(sys.modules, "pyodide.http", SimpleNamespace(pyfetch=disconnected))
        asyncio.run(run._browser_command(payload))
    else:
        run.transport = disconnected
        run._desktop_command(payload)
    run.update()
    assert run.data["state"] == "uncertain"
    run.command("retry")
    assert not run.busy
    game.menu.quantum.run = run
    game.menu.open("quantum")
    assert "quantum:retry" not in [b[0] for b in game.menu.buttons()]
    assert "quantum:status" in [b[0] for b in game.menu.buttons()]
