"""Quantum lab screens, using the game's own pixel panels and typography."""

import time
import pygame
from scripts.quantum_run import QuantumRun
from scripts.pillar_map import PillarMap
from scripts.circuit_view import CircuitView
from scripts.scroll_view import ScrollView


class QuantumMenu:
    def __init__(self, menu):
        self.menu = menu
        self.run = None
        self.history = None
        self.return_page = "complete"
        self.history_return = "main"
        self.result_scroll = ScrollView((78, 274, 640, 155), (640, 0), wheel_rect=(60, 196, 680, 279))
        self.history_offset = 0
        self._outcome_data = None
        self._outcomes = []
        self.pillar_map = None
        self.circuit_view = None
        self.circuit_return = "quantum"
        self.map_return = "quantum"

    def update(self):
        if self.run is not None and self.run is not self.menu.game.quantum_run:
            self.run.update()
        if self.history is not None:
            self.history.update()

    def open_run(self):
        self.run = self.menu.game.quantum_run
        if self.run is None:
            return
        self.return_page = "complete"
        self.result_scroll.y = 0
        self.run.open()
        self.menu.open("quantum")

    def open_history(self):
        self.history_return = self.menu.page
        self.history = QuantumRun({})
        self.history.command("history")
        self.history_offset = 0
        self.menu.open("quantum_history")

    def outcomes(self):
        data = self.run.data
        if data is not self._outcome_data:
            counts = data.get("counts", {})
            self._outcomes = sorted(set(counts) | set(data.get("ideal", {})), key=lambda k: (-counts.get(k, 0), k))
            self._outcome_data = data
            self.result_scroll.resize((640, len(self._outcomes) * 31))
        return self._outcomes

    def cancel_scroll_drag(self):
        self.result_scroll.drag = None
        if self.circuit_view:
            self.circuit_view.scroll.drag = None
            self.circuit_view.pressed_gate = None

    def handle_event(self, event):
        if self.menu.page == "quantum_circuit":
            return self.circuit_view.handle_event(event)
        if self.menu.page == "quantum" and self.run and self.run.data["state"] == "done":
            self.outcomes()
            return self.result_scroll.handle_event(event)
        return False

    def buttons(self):
        page = self.menu.page
        result = [("back", pygame.Rect(60, 499, 160, 42), "Back", "")]
        if page == "quantum_history":
            runs = self.history.data.get("runs", [])
            for i, run in enumerate(runs[self.history_offset:self.history_offset + 4]):
                label = f"Level {run['level']:02}  /  {run.get('backend', 'Quantum Inspire')}"
                result.append((f"quantum:history:{self.history_offset+i}", pygame.Rect(60, 195+i*68, 680, 56), label,
                               run["state"].upper()))
            if not self.history.busy:
                result.append(("quantum:refresh_history", pygame.Rect(560, 499, 180, 42), "Refresh", ""))
            if len(runs) > 4:
                result.extend(self.paging("history", self.history_offset, len(runs), 4))
            return result
        if page == "quantum_map":
            return result + self.pillar_map.buttons()
        if page == "quantum_circuit":
            return result
        data = self.run.data
        state = data["state"]
        if state in ("done", "failed") and "operations" in (self.run.circuit or {}):
            result.append(("quantum:again", pygame.Rect(560, 119, 180, 42), "Run again", ""))
        if not self.run.busy:
            if state == "ready":
                result.append(("quantum:submit", pygame.Rect(456, 499, 284, 42), f"Run {data['shots']:,} shots", ""))
            elif state in ("idle", "setup", "unavailable") and self.run.circuit:
                result.append(("quantum:prepare", pygame.Rect(456, 499, 284, 42), "Check hardware", ""))
            elif state in ("uncertain", "submitting", "queued", "running"):
                result.append(("quantum:status", pygame.Rect(456, 499, 284, 42), "Check status", ""))
        if state == "done":
            if "operations" in (self.run.circuit or {}) or data.get("diagram"):
                result.append(("quantum:circuit", pygame.Rect(364, 499, 180, 42), "View circuit", ""))
            result.append(("quantum:map", pygame.Rect(560, 499, 180, 42), "Pillar map", ""))
        return result

    @staticmethod
    def paging(kind, offset, total, size):
        result = []
        left, right = 236, 386
        if offset:
            result.append(("quantum:" + kind + ":prev", pygame.Rect(left, 499, 136, 42), "Previous", ""))
        if offset + size < total:
            result.append(("quantum:" + kind + ":next", pygame.Rect(right, 499, 136, 42), "Next", ""))
        return result

    def activate(self, action):
        if action == "quantum_run":
            self.open_run()
        elif action == "quantum:circuit":
            if (self.menu.page != "quantum" or self.run is None or self.run.data["state"] != "done"
                    or not ("operations" in (self.run.circuit or {}) or self.run.data.get("diagram"))):
                return
            self.circuit_return = self.menu.page
            self.circuit_view = CircuitView(self.menu, self.run)
            self.menu.open("quantum_circuit")
        elif action == "quantum_history":
            self.open_history()
        elif action == "quantum:refresh_history":
            self.history.command("history")
        elif action.startswith("quantum:history:") and action.split(":")[-1].isdigit():
            entry = self.history.data["runs"][int(action.split(":")[-1])]
            self.run = QuantumRun({"labels": entry["labels"], "level": entry["level"]})
            self.run.request_id = entry["request_id"]
            self.run.data = {**entry, "state": "queued", "message": "Loading saved run..."}
            self.return_page = "quantum_history"
            self.result_scroll.y = 0
            self.run.command("status")
            self.menu.open("quantum")
        elif action == "quantum:map":
            self.map_return = self.menu.page
            self.pillar_map = PillarMap(self.menu, self.run)
            self.menu.open("quantum_map")
        elif action.startswith("quantum:pillar:"):
            self.pillar_map.selected = int(action.split(":")[-1])
            self.menu.focus = self.pillar_map.selected + 1
        elif action == "quantum:again":
            previous = self.run
            self.run = QuantumRun(previous.circuit, transport=previous.transport)
            if previous is self.menu.game.quantum_run:
                self.menu.game.quantum_run = self.run
            self.result_scroll.y = 0
            self.run.open()
        elif action in ("quantum:history:next", "quantum:history:prev"):
            step = 1 if action.endswith("next") else -1
            self.history_offset += step * 4
        elif action in ("quantum:submit", "quantum:prepare", "quantum:status"):
            self.run.command(action.split(":")[-1])

    def back(self):
        page = self.menu.page
        if page == "quantum_map":
            self.menu.open(self.map_return)
        elif page == "quantum_circuit":
            self.menu.open(self.circuit_return)
        elif page == "quantum_history":
            self.menu.open(self.history_return)
        else:
            self.menu.open(self.return_page)

    def wrap(self, value, x, y, width=630, size=22, color=None):
        from scripts.common_functions import font
        from scripts.menus import MUTED
        words = str(value).split()
        line = ""
        for word in words:
            if font(size).size((line + " " + word).strip())[0] > width and line:
                self.menu.text(line, x, y, size, color or MUTED)
                line, y = word, y + size + 3
            else:
                line = (line + " " + word).strip()
        if line:
            self.menu.text(line, x, y, size, color or MUTED)
        return y + size + 3

    def draw(self):
        from scripts.menus import ACCENT, BG, EDGE, INK, MINT, MUTED, PANEL, RED
        menu, screen = self.menu, self.menu.game.screen
        screen.blit(menu.background, (0, 0))
        menu.draw_header()
        menu.text("QUANTUM INSPIRE", 658, 40, 20, ACCENT, True)
        if menu.page == "quantum_history":
            menu.text("Hardware runs", 60, 112, 43)
            menu.text("Your recent runs on this computer.", 62, 161, 22, MUTED)
            if self.history.busy:
                menu.text("Loading runs...", 80, 242, 27, ACCENT)
            elif not self.history.data.get("runs"):
                self.wrap(self.history.data.get("message") or "No hardware runs yet. Complete a level to send its circuit.", 80, 242)
            return
        run, data = self.run, self.run.data
        labels = data.get("labels", (run.circuit or {}).get("labels", []))
        level = data.get("level", (run.circuit or {}).get("level", menu.game.current_level))
        title = {"quantum_map": "Pillar map", "quantum_circuit": "Your circuit"}.get(menu.page, "Quantum lab")
        menu.text(title, 60, 112, 43)
        menu.text(f"LEVEL {level:02}  /  {len(labels)} {'PILLAR' if len(labels) == 1 else 'PILLARS'}", 62, 161, 20, MUTED)
        if menu.page == "quantum_map":
            self.pillar_map.draw()
            return
        if menu.page == "quantum_circuit":
            self.circuit_view.draw()
            return
        pygame.draw.rect(screen, PANEL, (60, 196, 680, 279))
        pygame.draw.rect(screen, EDGE, (60, 196, 680, 279), 1)
        state = data["state"]
        if state == "done":
            from scripts.common_functions import font

            def right_text(value, right, y, color=INK, size=20):
                menu.text(value, right - font(size).size(value)[0], y, size, color)

            actual, requested = data["actual_shots"], data["shots"]
            menu.text(f"{data['backend']}  /  {actual:,} of {requested:,} shots", 80, 209, 24, MINT)
            pygame.draw.rect(screen, BG, (78, 240, 640, 34))
            menu.text("OUTCOME", 88, 249, 18, MUTED)
            menu.text("MEASURED", 316, 249, 18, ACCENT)
            right_text("COUNT", 594, 249, MUTED, 18)
            right_text("IDEAL", 700, 249, MINT, 18)
            outcomes = self.outcomes()
            scroll = self.result_scroll
            first = int(scroll.y // 31)
            last = min(len(outcomes), int((scroll.y + scroll.rect.height) // 31) + 1)
            clip = screen.get_clip()
            screen.set_clip(scroll.rect)
            for i in range(first, last):
                bits = outcomes[i]
                y = round(278 + i * 31 - scroll.y)
                if i % 2:
                    pygame.draw.rect(screen, (32, 35, 50), (scroll.rect.x, y-4, scroll.rect.width, 31))
                count = data["counts"].get(bits, 0)
                probability = count / actual
                menu.text(bits, 88, y, 20)
                pygame.draw.rect(screen, EDGE, (316, y+4, 100, 11))
                pygame.draw.rect(screen, ACCENT, (316, y+4, round(100*probability), 11))
                right_text(f"{probability:.1%}", 477, y, ACCENT)
                right_text(f"{count:,}", 594, y)
                right_text(f"{data.get('ideal', {}).get(bits, 0):.1%}", 700, y, MINT)
            screen.set_clip(clip)
            pygame.draw.rect(screen, EDGE, (78, 240, 640, scroll.rect.bottom - 240), 1)
            pygame.draw.line(screen, EDGE, (78, 273), (717, 273))
            for x in (298, 493, 616):
                pygame.draw.line(screen, EDGE, (x, 240), (x, scroll.rect.bottom-1))
            scroll.draw(screen)
            menu.text(f"{len(outcomes)} outcomes  /  Job {data.get('job_id', '-')}  /  Scroll to explore", 80, 448, 18, MUTED)
            note = "Partial results. " if actual < requested else ""
            menu.text(note + "Hardware noise and rotation rounding can change results.", 60, 571, 18, MUTED)
            return
        titles = {"idle": "Checking hardware", "setup": "Connect your account", "unavailable": "Hardware unavailable",
                  "ready": "Ready to run", "submitting": "Sending circuit", "queued": "In the queue",
                  "running": "Measuring on hardware", "uncertain": "Check your submission", "failed": "Run did not finish"}
        title = "Connecting..." if run.busy and state in ("idle", "setup", "unavailable") else titles.get(state, "Quantum Inspire")
        menu.text(title, 80, 219, 31, RED if state == "failed" else ACCENT)
        y = self.wrap(data.get("message", ""), 80, 263)
        if state == "setup":
            menu.text("One-time setup in your game environment:", 80, max(318, y+10), 21, INK)
            menu.text("python -m pip install -r requirements-quantum.txt", 80, max(349, y+41), 21, ACCENT)
            menu.text("qi login", 80, max(376, y+68), 21, ACCENT)
            menu.text("Browser: python -m scripts.quantum_server", 80, max(416, y+108), 21, MUTED)
        elif state == "ready":
            menu.text(f"{data['backend']}  /  {data['shots']:,} shots  /  depth {data['depth']}", 80, 333, 25, MINT)
            self.wrap("A shot runs your circuit once and measures the pillars. Hardware noise and 5-degree rotation rounding may change the results.", 80, 378, size=21)
        elif state in ("queued", "running", "submitting", "uncertain"):
            menu.text(f"{data.get('backend', 'Quantum Inspire')}  /  Job {data.get('job_id', 'pending')}", 80, 353, 23, MINT)
            self.wrap("You can go back and keep playing. Open Hardware runs from the main menu to return to this job.", 80, 398, size=21)
        footer = "This is taking longer than usual. You can go back while the connection finishes." if run.busy and time.monotonic() - run.started > 30 else "ESC  Back"
        menu.text(footer, 60, 571, 18, MUTED)
