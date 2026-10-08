// A hidden browser tab must pause just like an unfocused desktop window.
window.qungeonPauseRequested = false;
window.addEventListener("blur", () => { window.qungeonPauseRequested = true; });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) window.qungeonPauseRequested = true;
});

const canvas = document.getElementById("canvas");
function resizeCanvas() {
  const ratio = window.devicePixelRatio || 1;
  const fit = Math.min(window.innerWidth / 800, window.innerHeight / 600) * ratio;
  // Whole physical pixels preserve the original art and font spacing.
  const scale = fit >= 1 ? Math.floor(fit) : fit;
  canvas.style.width = `${800 * scale / ratio}px`;
  canvas.style.imageRendering = fit >= 1 ? "pixelated" : "auto";
}
window.addEventListener("resize", resizeCanvas);
window.visualViewport?.addEventListener("resize", resizeCanvas);
resizeCanvas();

canvas.addEventListener("pointerdown", () => canvas.focus());
canvas.addEventListener("keydown", (event) => {
  if (["Tab", " ", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "PageUp", "PageDown", "Home", "End"].includes(event.key)) {
    event.preventDefault();
  }
});

// Python polls completed requests once per frame; no Python callbacks run here.
let levelWorker;
let levelPhase = "idle";
let levelRequest = 0;
const levelResults = new Map();
const levelPending = new Set();
function ensureLevelWorker() {
  if (!levelWorker) {
    levelPhase = "preparing";
    levelWorker = new Worker(new URL("./web/level-check-worker.js?v=16", document.baseURI), { type: "module" });
    levelWorker.onmessage = ({ data: { id, result, phase } }) => {
      if (phase) levelPhase = phase;
      if (levelPending.delete(id)) levelResults.set(id, result);
    };
    levelWorker.onerror = (event) => {
      event.preventDefault();
      for (const id of levelPending) levelResults.set(id, JSON.stringify({
        solvable: null, message: "Could not start the level checker. Please try again.",
      }));
      levelPending.clear();
      levelWorker.terminate();
      levelWorker = undefined;
      levelPhase = "error";
    };
  }
}
window.qungeonPrepareLevelChecker = () => {
  ensureLevelWorker();
  if (levelPhase === "preparing" || levelPhase === "error") {
    levelWorker.postMessage({ prepare: true });
  }
};
window.qungeonLevelCheckerPhase = () => levelPhase;
window.qungeonCheckLevel = (payload) => {
  ensureLevelWorker();
  const id = ++levelRequest;
  levelPending.add(id);
  levelWorker.postMessage({ id, payload });
  return id;
};
window.qungeonPollLevel = (id) => {
  const result = levelResults.get(id) || "";
  levelResults.delete(id);
  return result;
};
window.qungeonCancelLevel = (id) => {
  levelResults.delete(id);
  if (levelPending.delete(id)) {
    levelWorker?.terminate();
    levelWorker = undefined;
    levelPhase = "idle";
    levelPending.clear();
  }
};
