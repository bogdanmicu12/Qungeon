"""Exercise the browser bridge over HTTP, including its local account boundary."""

import http.client
import json
import threading
from types import SimpleNamespace

import pytest
from scripts.quantum_server import create_server


@pytest.fixture
def server():
    calls = []
    def command(payload):
        calls.append(payload)
        return {"state": "ready"}
    service = SimpleNamespace(command=command)
    server = create_server(0, service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, calls
    server.shutdown()
    server.server_close()
    thread.join(2)


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    connection.request(method, path, body, headers or {})
    response = connection.getresponse()
    status, data = response.status, response.read()
    connection.close()
    return status, data


def test_same_origin_flow_and_public_assets(server):
    app, calls = server
    status, body = request(app, "POST", "/api/quantum", json.dumps({"action": "status"}),
                           {"Content-Type": "application/json", "X-Qungeon": "1",
                            "Origin": f"http://127.0.0.1:{app.server_port}"})
    assert status == 200 and json.loads(body)["state"] == "ready"
    assert calls == [{"action": "status"}]
    assert request(app, "GET", "/?level=1")[0] == 200
    assert request(app, "GET", "/scripts/quantum_run.py")[0] == 200
    assert request(app, "GET", "/scripts/circuit_view.py")[0] == 200
    assert request(app, "GET", "/scripts/scroll_view.py")[0] == 200


@pytest.mark.parametrize("path", ["/.git/config", "/.qungeon-quantum/foo.json", "/.env", "/scripts/quantum_service.py",
                                 "/assets/", "/%2e%2e/README.md", "/QungeonEnv313/pyvenv.cfg"])
def test_private_files_and_directory_listings_are_blocked(server, path):
    assert request(server[0], "GET", path)[0] == 404


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://evil.example"}, {"Host": "evil.example"},
                                     {"Content-Type": "text/plain"}])
def test_cross_origin_and_rebinding_cannot_spend_account_shots(server, headers):
    base = {"Content-Type": "application/json", "X-Qungeon": "1"}
    if not headers:
        base.pop("X-Qungeon")
    base.update(headers)
    assert request(server[0], "POST", "/api/quantum", "{}", base)[0] == 403
    assert not server[1]
