"""Nonblocking level checks: a subprocess on desktop, a Web Worker in browsers."""

import json
import sys
import time


class LevelCheckJob:
    TIMEOUT = 180

    @staticmethod
    def prepare():
        if sys.platform == "emscripten":
            from js import window

            window.qungeonPrepareLevelChecker()

    @property
    def phase(self):
        if self.browser:
            return str(self.window.qungeonLevelCheckerPhase())
        return "checking"

    def __init__(self, data):
        self.started = time.monotonic()
        self.closed = False
        self.browser = sys.platform == "emscripten"
        payload = json.dumps(data)
        if self.browser:
            from js import window

            self.window = window
            self.request = window.qungeonCheckLevel(payload)
        else:
            import subprocess
            import tempfile
            from pathlib import Path

            self.directory = tempfile.TemporaryDirectory(prefix="qungeon-level-")
            folder = Path(self.directory.name)
            source = folder / "input.json"
            self.result = folder / "result.json"
            source.write_text(payload, encoding="utf-8")
            try:
                self.process = subprocess.Popen(
                    [sys.executable, "-m", "scripts.level_check", str(source), str(self.result)],
                    cwd=Path(__file__).resolve().parents[1],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                self.directory.cleanup()
                raise

    def poll(self):
        if self.closed:
            return None
        if time.monotonic() - self.started > self.TIMEOUT:
            self.cancel()
            return {"solvable": None, "message": "Level check timed out. Please try again."}
        if self.browser:
            value = self.window.qungeonPollLevel(self.request)
            if not value:
                return None
            self.closed = True
            return json.loads(str(value))
        if self.process.poll() is None:
            return None
        try:
            result = json.loads(self.result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = {"solvable": None, "message": "Level check failed. Please try again."}
        self.closed = True
        self.directory.cleanup()
        return result

    def cancel(self):
        if self.closed:
            return
        self.closed = True
        if self.browser:
            self.window.qungeonCancelLevel(self.request)
        else:
            if self.process.poll() is None:
                self.process.kill()
            # Reap the child and clean up files without waiting on the UI thread.
            import threading

            def cleanup():
                self.process.wait()
                self.directory.cleanup()

            threading.Thread(target=cleanup, daemon=True).start()
