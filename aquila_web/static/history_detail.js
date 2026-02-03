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
      <div><strong>Result</strong><span>${entry.result || "--"}</span></div>
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
