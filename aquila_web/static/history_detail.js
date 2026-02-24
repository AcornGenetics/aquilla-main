const TUBE_NAME_KEY = "aqTubeNames";
const DEFAULT_TUBE_NAMES = ["Tube 1", "Tube 2", "Tube 3", "Tube 4"];

const getTubeNames = () => {
  try {
    const stored = localStorage.getItem(TUBE_NAME_KEY);
    if (!stored) {
      return DEFAULT_TUBE_NAMES.slice();
    }
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) {
      return DEFAULT_TUBE_NAMES.slice();
    }
    return DEFAULT_TUBE_NAMES.map((fallback, index) => {
      const value = parsed[index];
      return typeof value === "string" && value.trim() ? value.trim() : fallback;
    });
  } catch (error) {
    return DEFAULT_TUBE_NAMES.slice();
  }
};

const formatResultLabels = (result) => {
  if (typeof result !== "string") {
    return result;
  }
  const tubeNames = getTubeNames();
  return tubeNames.reduce((updated, name, index) => {
    const pattern = new RegExp(`\\bTube ${index + 1}\\b`, "g");
    return updated.replace(pattern, name);
  }, result);
};

async function loadRunDetail() {
  const container = document.getElementById("run-detail");
  if (!container) {
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const indexParam = params.get("index");
  const index = indexParam ? Number(indexParam) : null;
  if (index === null || Number.isNaN(index)) {
    container.textContent = "Run not found";
    return;
  }

  try {
    const response = await fetch("/history/data");
    if (!response.ok) {
      throw new Error("Failed to load history");
    }
    const entries = await response.json();
    const entry = entries[index];
    if (!entry) {
      container.textContent = "Run not found";
      return;
    }

    container.innerHTML = "";
    const meta = document.createElement("div");
    meta.className = "run-detail__meta";
    meta.innerHTML = `
      <div><strong>Date</strong><span>${entry.timestamp || "--"}</span></div>
      <div><strong>Profile</strong><span>${entry.profile || "--"}</span></div>
      <div><strong>Run Name</strong><span>${entry.run_name || "--"}</span></div>
      <div><strong>Result</strong><span>${formatResultLabels(entry.result || "--")}</span></div>
    `;
    container.appendChild(meta);

    const graphWrapper = document.createElement("div");
    graphWrapper.className = "run-detail__graph";
    if (entry.graph_path) {
      const img = document.createElement("img");
      img.src = entry.graph_path;
      img.alt = "Run graph";
      graphWrapper.appendChild(img);
    } else {
      graphWrapper.textContent = "No graph available";
    }
    container.appendChild(graphWrapper);
  } catch (error) {
    console.error("Failed to load run detail", error);
    container.textContent = "Failed to load run detail";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadRunDetail();
});
