// A separate Python runtime keeps both dependency imports and search off the UI.
let runtime;

async function initialize() {
  const indexURL = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
  const { loadPyodide } = await import(`${indexURL}pyodide.mjs`);
  const pyodide = await loadPyodide({ indexURL });
  await pyodide.loadPackage("micropip");

  const response = await fetch(new URL("./pyscript.json?v=16", import.meta.url));
  if (!response.ok) throw new Error("Could not load level checker configuration");
  const config = await response.json();
  const scripts = new Set([
    "level_check", "level_solver", "level_validation", "quantum_rules", "flip_phase", "swap",
  ]);
  await Promise.all(Object.entries(config.files).filter(([, target]) => {
    return target.startsWith("./unitary/") || scripts.has(target.split("/").pop().replace(".py", ""));
  }).map(async ([source, target]) => {
    const file = await fetch(new URL(source, import.meta.url));
    if (!file.ok) throw new Error(`Could not load ${source}`);
    const path = `/home/pyodide/${target.replace(/^\.\//, "")}`;
    pyodide.FS.mkdirTree(path.slice(0, path.lastIndexOf("/")));
    pyodide.FS.writeFile(path, await file.text());
  }));
  await pyodide.runPythonAsync(`
import micropip
await micropip.install("cirq-core==1.7.0")
import json
from scripts.level_check import check_level
# Import the full solver during preparation, even when the first level fails
# format validation. A deferred Cirq import otherwise makes the first real
# search take seconds despite the worker already claiming to be ready.
from scripts.level_solver import solve_level_data
`);
  return pyodide;
}

self.onmessage = async ({ data: { id, payload, prepare } }) => {
  try {
    if (!runtime) self.postMessage({ phase: "preparing" });
    runtime ??= initialize();
    const pyodide = await runtime;
    self.postMessage({ phase: "ready" });
    if (prepare) return;
    self.postMessage({ phase: "checking" });
    pyodide.globals.set("level_payload", payload);
    const result = pyodide.runPython("json.dumps(check_level(json.loads(level_payload)))");
    self.postMessage({ id, result });
    self.postMessage({ phase: "ready" });
  } catch (error) {
    // Retry initialization on the next request after a network/import failure.
    runtime = undefined;
    self.postMessage({ phase: "error" });
    if (prepare) return;
    self.postMessage({ id, result: JSON.stringify({
      solvable: null, message: `Level check failed: ${error.message}`,
    }) });
  }
};
