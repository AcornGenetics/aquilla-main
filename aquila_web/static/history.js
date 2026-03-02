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

    entries.slice().reverse().forEach((entry, displayIndex) => {
      const actualIndex = entries.length - 1 - displayIndex;
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
      resultCell.textContent = formatResultLabels(entry.result || "--");
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

      tableBody.appendChild(row);
    });
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
    const runLabel = selectedNames.length === 1 ? selectedNames[0] : `${selectedNames.length} runs`;
    const confirmed = window.confirm(`Are you sure you want to delete ${runLabel}?`);
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
