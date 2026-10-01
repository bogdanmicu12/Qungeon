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