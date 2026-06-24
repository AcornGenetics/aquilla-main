const esc = (str) =>
  String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const TUBE_NAME_KEY = "aqTubeNames";
const DEFAULT_TUBE_NAMES = ["Tube 1", "Tube 2", "Tube 3", "Tube 4"];

const normalizeTubeNames = (names) =>
  DEFAULT_TUBE_NAMES.map((fallback, index) => {
    const value = Array.isArray(names) ? names[index] : null;
    return typeof value === "string" && value.trim() ? value.trim() : fallback;
  });

const resolveTubeNames = (entry) => {
  if (entry && Array.isArray(entry.tube_names)) {
    return normalizeTubeNames(entry.tube_names);
  }
  return DEFAULT_TUBE_NAMES.slice();
};

const formatResultLabels = (result, tubeNames) => {
  if (typeof result !== "string") {
    return result;
  }
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

const formatResultSummary = (perTube, tubeNames) => {
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

// Channel Calls in Well-Verdict precedence order: Detected > Inconclusive > Not Detected.
const CALL_PRECEDENCE = ["Detected", "Inconclusive", "Not Detected"];
const normalizeCall = (value) => (CALL_PRECEDENCE.includes(value) ? value : "Not Detected");

const summarizeResults = (resultsData, labels = {}, tubeNames = DEFAULT_TUBE_NAMES.slice()) => {
  const perTube = tubeNames.map(() => "not-detected");
  const perTubeLabel = tubeNames.map(() => "");
  if (!resultsData || typeof resultsData !== "object") {
    return { perTube, perTubeLabel, detectedCount: 0, inconclusiveCount: 0, anyChannelInconclusive: false };
  }

  const famLabel = labels.fam || "FAM";
  const roxLabel = labels.rox || "ROX";
  let anyChannelInconclusive = false;

  for (let tube = 1; tube <= 4; tube += 1) {
    const fam = resultsData?.["1"]?.[String(tube)];
    const rox = resultsData?.["2"]?.[String(tube)];

    // Channels in FAM-then-ROX order. A "ROX Unavailable" Call is excluded
    // entirely (it is not a result); the remaining Calls are normalized.
    const channels = [
      { name: famLabel, call: fam },
      { name: roxLabel, call: rox },
    ]
      .filter((c) => c.call !== "ROX Unavailable")
      .map((c) => ({ name: c.name, call: normalizeCall(c.call) }));

    // QC is channel-sensitive: an Inconclusive Channel flags the run even when
    // the Well Verdict is Detected (Detected-wins must not mask it).
    if (channels.some((c) => c.call === "Inconclusive")) {
      anyChannelInconclusive = true;
    }

    // Verdict: highest-precedence Call present across the Well's Channels.
    if (channels.some((c) => c.call === "Detected")) {
      perTube[tube - 1] = "detected";
    } else if (channels.some((c) => c.call === "Inconclusive")) {
      perTube[tube - 1] = "inconclusive";
    }

    // Label: group Channels by Call in precedence order, FAM before ROX within a group.
    perTubeLabel[tube - 1] = CALL_PRECEDENCE.flatMap((status) => {
      const names = channels.filter((c) => c.call === status).map((c) => c.name);
      return names.length ? [`${status} (${names.join(" + ")})`] : [];
    }).join(" ");
  }

  const detectedCount = perTube.filter((value) => value === "detected").length;
  const inconclusiveCount = perTube.filter((value) => value === "inconclusive").length;
  return { perTube, perTubeLabel, detectedCount, inconclusiveCount, anyChannelInconclusive };
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
    const tubeNames = resolveTubeNames(entry);

    const resultsData = await loadResultsData(entry);
    const summary = summarizeResults(resultsData, entry.labels || {}, tubeNames);
    const qcStatus = summary.anyChannelInconclusive ? "Review" : "Pass";
    const resultText = resultsData
      ? formatResultSummary(summary.perTube, tubeNames)
      : formatResultLabels(entry.result || "--", tubeNames);
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
            <div class="run-detail-value">${esc(entry.timestamp || "--")}</div>
          </div>
          <div>
            <div class="run-detail-label">Profile</div>
            <div class="run-detail-value">${esc(entry.profile || "--")}</div>
          </div>
          <div>
            <div class="run-detail-label">Run Name</div>
            <div class="run-detail-value">${esc(entry.run_name || "--")}</div>
          </div>
          <div>
            <div class="run-detail-label">Result</div>
            <div class="run-detail-value">${esc(resultText)}</div>
          </div>
        </div>
        <div class="run-detail-pills">
          ${summary.perTube
            .map((status, index) => {
              const label = `${tubeNames[index]}: ${summary.perTubeLabel[index]}`;
              return `<span class="run-detail-pill run-detail-pill--${status}">${esc(label)}</span>`;
            })
            .join("")}
        </div>
      </section>
      <section class="run-detail-card">
        <div class="run-detail-card__header">Amplification Curves</div>
        <div class="run-detail-card__subheader">Real-time qPCR fluorescence data</div>
        <div class="run-detail-graph">
          ${entry.graph_path
            ? `<img src="${esc(entry.graph_path)}" alt="Run graph" />`
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

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    loadRunDetail();
  });
}

// Enable unit testing under Node (node:test) without affecting the browser,
// where `module` is undefined. Not a build step — a guarded CommonJS export.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { summarizeResults };
}
