"""Personal, loopback-only browser launcher: python -m scripts.quantum_server.

Serves only the game's public assets and a same-origin Quantum Inspire bridge.
It is deliberately not a shared hosting backend: runs use the local QI account.
"""

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from scripts.quantum_service import default_service

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 350_000


def public_files():
    files = {"index.html", "Qungeon.py", "web/main.py", "web/pyscript.json", "web/styles.css", "web/shell.js"}
    config = json.loads((ROOT / "web/pyscript.json").read_text(encoding="utf-8"))
    for name in config["files"]:
        path = (ROOT / "web" / name).resolve()
        if path.is_relative_to(ROOT):
            files.add(path.relative_to(ROOT).as_posix())
    return files


class QuantumHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def trusted_host(self):
        return self.headers.get("Host") in {f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}

    def send_head(self):
        if not self.trusted_host():
            self.send_error(403)
            return None
        path = (ROOT / unquote(urlsplit(self.path).path).lstrip("/")).resolve()
        if path == ROOT:
            path = ROOT / "index.html"
        if not path.is_relative_to(ROOT) or path.relative_to(ROOT).as_posix() not in self.server.public_files:
            self.send_error(404)
            return None
        return super().send_head()

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid content length")
            return
        if not 0 < length <= MAX_BODY:
            self.send_error(413)
            return
        # Drain the bounded body even when rejecting a request. Closing a socket
        # with unread bytes can turn our 403 into a TCP reset on Windows.
        raw = self.rfile.read(length)
        origin = self.headers.get("Origin")
        if (not self.trusted_host() or (origin is not None and origin != "http://" + self.headers["Host"])
                or self.headers.get("X-Qungeon") != "1"
                or self.headers.get_content_type() != "application/json"):
            self.send_error(403)
            return
        if self.path != "/api/quantum":
            self.send_error(404)
            return
        try:
            payload = json.loads(raw)
            result = self.server.quantum_service.command(payload)
        except (ValueError, TypeError, KeyError):
            self.send_error(400, "Invalid quantum request")
            return
        except Exception:
            self.send_error(503, "Quantum service unavailable")
            return
        body = json.dumps(result, allow_nan=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # The persisted run is still available when the player returns.

    def log_message(self, format, *args):
        pass


def create_server(port=8000, service=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), QuantumHandler)
    server.quantum_service = service or default_service()
    server.public_files = public_files()
    return server


def main():
    parser = argparse.ArgumentParser(description="Play Qungeon with your local Quantum Inspire account.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    with create_server(args.port) as server:
        print(f"Qungeon: http://localhost:{server.server_port}")
        print("Quantum runs use the account connected with qi login. Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
