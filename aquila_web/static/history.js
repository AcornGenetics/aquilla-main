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

const formatResultLabels = (result, entry) => {
  if (typeof result !== "string") {
    return result;
  }
  const tubeNames = resolveTubeNames(entry);
  return tubeNames.reduce((updated, name, index) => {
    const pattern = new RegExp(`\\bTube ${index + 1}\\b`, "g");
    return updated.replace(pattern, name);
  }, result);
};

const summarizeResults = (resultsData, tubeNames) => {
  const perTube = tubeNames.map(() => "not-detected");
  if (!resultsData || typeof resultsData !== "object") {
    return perTube;
  }
  for (let tube = 1; tube <= 4; tube += 1) {
    const fam = resultsData?.["1"]?.[String(tube)];
    const rox = resultsData?.["2"]?.[String(tube)];
    if (fam === "Inconclusive" || rox === "Inconclusive") {
      perTube[tube - 1] = "inconclusive";
    } else if (fam === "Detected" || rox === "Detected") {
      perTube[tube - 1] = "detected";
    }
  }
  return perTube;
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

const fetchResultText = async (entry, tubeNames) => {
  const resultsPath = entry?.results_path;
  if (!resultsPath) {
    return formatResultLabels(entry.result || "--", entry);
  }
  try {
    const response = await fetch(`/results/by-path?path=${encodeURIComponent(resultsPath)}`);
    if (!response.ok) {
      return formatResultLabels(entry.result || "--", entry);
    }
    const data = await response.json();
    if (data?.data?.failed) {
      return formatResultLabels(entry.result || "--", entry);
    }
    const perTube = summarizeResults(data, tubeNames);
    return formatResultSummary(perTube, tubeNames);
  } catch {
    return formatResultLabels(entry.result || "--", entry);
  }
};

async function loadHistory() {
  const tableBody = document.getElementById("history-table-body");
  if (!tableBody) {
    return;
  }

  try {
    const response = await fetch("/history/data");
    if (!response.ok) {
      throw new Error("Failed to load history");
    }
    const entries = await response.json();
    tableBody.innerHTML = "";

    if (!entries.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 6;
      cell.textContent = "No runs yet";
      row.appendChild(cell);
      tableBody.appendChild(row);
      return;
    }

    const rowPromises = entries.slice().reverse().map(async (entry, displayIndex) => {
      const actualIndex = entries.length - 1 - displayIndex;
      const tubeNames = resolveTubeNames(entry);
      const row = document.createElement("tr");
      const checkboxCell = document.createElement("td");
      checkboxCell.className = "checkbox-cell";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "history-checkbox";
      checkbox.dataset.index = String(actualIndex);
      checkboxCell.appendChild(checkbox);
      row.appendChild(checkboxCell);

      const dateCell = document.createElement("td");
      dateCell.textContent = entry.timestamp || "--";
      row.appendChild(dateCell);

      const runCell = document.createElement("td");
      runCell.textContent = entry.run_name || "--";
      row.appendChild(runCell);

      const profileCell = document.createElement("td");
      profileCell.textContent = entry.profile || "--";
      row.appendChild(profileCell);

      const resultCell = document.createElement("td");
      resultCell.textContent = await fetchResultText(entry, tubeNames);
      row.appendChild(resultCell);

      const graphCell = document.createElement("td");
      if (entry.graph_path) {
        const link = document.createElement("a");
        link.href = `/history/run?index=${encodeURIComponent(actualIndex)}`;
        link.className = "history-graph-link";
        link.textContent = "View";
        graphCell.appendChild(link);
      } else {
        graphCell.textContent = "--";
      }
      row.appendChild(graphCell);

      return row;
    });

    const rows = await Promise.all(rowPromises);
    rows.forEach((row) => tableBody.appendChild(row));
  } catch (error) {
    console.error("Failed to load history", error);
  }
}

function getSelectedIndices() {
  return Array.from(document.querySelectorAll(".history-checkbox"))
    .filter((box) => box.checked)
    .map((box) => Number(box.dataset.index))
    .filter((value) => !Number.isNaN(value));
}

async function deleteSelectedHistory() {
  try {
    const indices = getSelectedIndices();
    if (!indices.length) {
      return;
    }
    const selectedNames = indices
      .map((index) => {
        const row = document.querySelector(`.history-checkbox[data-index="${index}"]`)?.closest("tr");
        const runCell = row?.querySelector("td:nth-child(3)");
        return runCell?.textContent?.trim() || `Run ${index + 1}`;
      })
      .filter(Boolean);
    const confirmed = await confirmModal(historyDeleteCopy(selectedNames));
    if (!confirmed) {
      return;
    }
    const response = await fetch("/history/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ indices })
    });
    if (!response.ok) {
      throw new Error("Failed to delete history");
    }
    loadHistory();
  } catch (error) {
    console.error("Failed to delete history", error);
  }
}

function toggleSelectAll(checked) {
  document.querySelectorAll(".history-checkbox").forEach((box) => {
    box.checked = checked;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  loadHistory();
  const deleteButton = document.getElementById("history-clear");
  const selectAllCheckbox = document.getElementById("history-select-all-checkbox");
  if (deleteButton) {
    deleteButton.addEventListener("click", deleteSelectedHistory);
  }
  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener("change", (event) => {
      toggleSelectAll(event.target.checked);
    });
  }
});
