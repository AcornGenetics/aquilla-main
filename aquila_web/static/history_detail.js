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

const normalizeStatus = (value) => {
  if (value === "Detected") return "detected";
  if (value === "Inconclusive") return "inconclusive";
  return "not-detected";
};

const formatResultSummary = (perTube) => {
  const tubeNames = getTubeNames();
  const detectedLabels = [];
  const inconclusiveLabels = [];
  perTube.forEach((status, index) => {
    if (status === "detected") {
      detectedLabels.push(tubeNames[index]);
    } else if (status === "inconclusive") {
      inconclusiveLabels.push(`${tubeNames[index]} inconclusive`);
    }
  });
  if (!detectedLabels.length && !inconclusiveLabels.length) {
    return "No targets detected";
  }
  const parts = [];
  if (detectedLabels.length) {
    parts.push(`Detected: ${detectedLabels.join(", ")}`);
  }
  if (inconclusiveLabels.length) {
    parts.push(inconclusiveLabels.join(", "));
  }
  return parts.join(" · ");
};

const summarizeResults = (resultsData, labels = {}) => {
  const tubeNames = getTubeNames();
  const perTube = tubeNames.map(() => "not-detected");
  const perTubeDetectedLabels = tubeNames.map(() => []);
  if (!resultsData || typeof resultsData !== "object") {
    return { perTube, detectedCount: 0, inconclusiveCount: 0, perTubeDetectedLabels };
  }

  const famLabel = labels.fam || "FAM";
  const roxLabel = labels.rox || "ROX";

  for (let tube = 1; tube <= 4; tube += 1) {
    const fam = resultsData?.["1"]?.[String(tube)];
    const rox = resultsData?.["2"]?.[String(tube)];
    if (fam === "Inconclusive" || rox === "Inconclusive") {
      perTube[tube - 1] = "inconclusive";
    } else if (fam === "Detected" || rox === "Detected") {
      perTube[tube - 1] = "detected";
    }
    if (fam === "Detected") {
      perTubeDetectedLabels[tube - 1].push(famLabel);
    }
    if (rox === "Detected") {
      perTubeDetectedLabels[tube - 1].push(roxLabel);
    }
  }

  const detectedCount = perTube.filter((value) => value === "detected").length;
  const inconclusiveCount = perTube.filter((value) => value === "inconclusive").length;
  return { perTube, detectedCount, inconclusiveCount, perTubeDetectedLabels };
};

const loadResultsData = async (entry) => {
  const resultsPath = entry?.results_path;
  if (!resultsPath || typeof resultsPath !== "string") {
    return null;
  }
  try {
    await fetch("/results/path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: resultsPath })
    });
    const response = await fetch("/results");
    if (!response.ok) {
      return null;
    }
    const data = await response.json();
    if (data?.data?.failed) {
      return null;
    }
    return data;
  } catch (error) {
    return null;
  }
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

    const resultsData = await loadResultsData(entry);
    const summary = summarizeResults(resultsData, entry.labels || {});
    const qcStatus = summary.inconclusiveCount > 0 ? "Review" : "Pass";
    const resultText = resultsData ? formatResultSummary(summary.perTube) : formatResultLabels(entry.result || "--");
    const cqValues = [];
    if (resultsData?.cq) {
      for (let tube = 1; tube <= 4; tube += 1) {
        const famStatus = resultsData?.["1"]?.[String(tube)];
        const roxStatus = resultsData?.["2"]?.[String(tube)];
        const famCq = resultsData?.cq?.["1"]?.[String(tube)];
        const roxCq = resultsData?.cq?.["2"]?.[String(tube)];
        if (famStatus === "Detected" && Number.isFinite(famCq)) {
          cqValues.push(Number(famCq));
        }
        if (roxStatus === "Detected" && Number.isFinite(roxCq)) {
          cqValues.push(Number(roxCq));
        }
      }
    }
    const avgCq = cqValues.length
      ? Math.round((cqValues.reduce((sum, value) => sum + value, 0) / cqValues.length) * 100) / 100
      : null;

    container.innerHTML = `
      <section class="run-detail-card">
        <div class="run-detail-card__header">Run Information</div>
        <div class="run-detail-meta">
          <div>
            <div class="run-detail-label">Date</div>
            <div class="run-detail-value">${entry.timestamp || "--"}</div>
          </div>
          <div>
            <div class="run-detail-label">Profile</div>
            <div class="run-detail-value">${entry.profile || "--"}</div>
          </div>
          <div>
            <div class="run-detail-label">Run Name</div>
            <div class="run-detail-value">${entry.run_name || "--"}</div>
          </div>
          <div>
            <div class="run-detail-label">Result</div>
            <div class="run-detail-value">${resultText}</div>
          </div>
        </div>
        <div class="run-detail-pills">
          ${summary.perTube
            .map((status, index) => {
              const detectedLabels = summary.perTubeDetectedLabels[index];
              let labelDetail = "Not detected";
              if (status === "detected") {
                labelDetail = detectedLabels.length ? `Detected (${detectedLabels.join(" + ")})` : "Detected";
              } else if (status === "inconclusive") {
                labelDetail = "Inconclusive";
              }
              const label = `${getTubeNames()[index]}: ${labelDetail}`;
              return `<span class="run-detail-pill run-detail-pill--${status}">${label}</span>`;
            })
            .join("")}
        </div>
      </section>
      <section class="run-detail-card">
        <div class="run-detail-card__header">Amplification Curves</div>
        <div class="run-detail-card__subheader">Real-time qPCR fluorescence data</div>
        <div class="run-detail-graph">
          ${entry.graph_path
            ? `<img src="${entry.graph_path}" alt="Run graph" />`
            : "No graph available"}
        </div>
      </section>
      <section class="run-detail-kpis">
        <div class="run-detail-kpi">
          <div class="run-detail-kpi__value">${summary.detectedCount}/4</div>
          <div class="run-detail-kpi__label">Detected</div>
        </div>
        <div class="run-detail-kpi">
          <div class="run-detail-kpi__value">${summary.inconclusiveCount}/4</div>
          <div class="run-detail-kpi__label">Inconclusive</div>
        </div>
        <div class="run-detail-kpi">
          <div class="run-detail-kpi__value">${avgCq ?? "--"}</div>
          <div class="run-detail-kpi__label">Avg Ct Value</div>
        </div>
        <div class="run-detail-kpi">
          <div class="run-detail-kpi__value run-detail-kpi__value--${qcStatus.toLowerCase()}">${qcStatus}</div>
          <div class="run-detail-kpi__label">QC Status</div>
        </div>
      </section>
    `;
  } catch (error) {
    console.error("Failed to load run detail", error);
    container.textContent = "Failed to load run detail";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadRunDetail();
});
