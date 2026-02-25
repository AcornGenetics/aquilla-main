(() => {
  const tableBody = document.getElementById("profiles-table-body");
  const deleteButton = document.getElementById("profiles-delete-button");
  const selectAllCheckbox = document.getElementById("profiles-select-all");
  if (!tableBody) return;

  const formatDuration = (seconds) => {
    if (!Number.isFinite(seconds) || seconds <= 0) return "--:--:--";
    const total = Math.round(seconds);
    const hrs = Math.floor(total / 3600);
    const mins = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    return `${String(hrs).padStart(2, "0")}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  };

  const parseDuration = (value) => {
    if (Number.isFinite(value)) return Number(value);
    if (typeof value !== "string") return 0;
    const parts = value.split(":").map((part) => Number(part));
    if (parts.length !== 3 || parts.some((part) => !Number.isFinite(part))) return 0;
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  };

  const formatTimestamp = (timestamp) => {
    if (!Number.isFinite(timestamp)) return "--/--/-- --:--";
    const date = new Date(timestamp);
    const pad = (value) => String(value).padStart(2, "0");
    const month = pad(date.getMonth() + 1);
    const day = pad(date.getDate());
    const year = String(date.getFullYear()).slice(-2);
    const hours = pad(date.getHours());
    const minutes = pad(date.getMinutes());
    return `${month}/${day}/${year} ${hours}:${minutes}`;
  };

  const sumConfigurationDuration = (configuration) => {
    const stages = configuration?.stages || [];
    return stages.reduce((total, stage) => {
      const multiplier = Number(stage.multiplier) || 1;
      const stageTotal = (stage.steps || []).reduce((sum, step) => {
        return sum + parseDuration(step.duration);
      }, 0);
      return total + stageTotal * multiplier;
    }, 0);
  };

  const createCell = (text, className) => {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    cell.textContent = text;
    return cell;
  };

  const createActionButton = (label, handler) => {
    const wrapper = document.createElement("div");
    wrapper.className = "profiles-actions";
    const button = document.createElement("button");
    button.className = "profiles-action-btn profiles-action-btn--start";
    button.type = "button";
    button.textContent = label;
    if (handler) {
      button.addEventListener("click", handler);
    }
    wrapper.appendChild(button);
    return wrapper;
  };

  const createActionLink = (label, href) => {
    const wrapper = document.createElement("div");
    wrapper.className = "profiles-actions";
    const link = document.createElement("a");
    link.className = "profiles-action-btn profiles-action-btn--edit";
    link.href = href;
    link.textContent = label;
    wrapper.appendChild(link);
    return wrapper;
  };

  const buildRow = (profile) => {
    const row = document.createElement("tr");
    const checkboxCell = document.createElement("td");
    checkboxCell.className = "checkbox-cell";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "profile-checkbox";
    checkbox.dataset.profileId = profile.id || "";
    checkbox.dataset.profileName = profile.name || profile.label || profile.id || "profile";
    checkbox.addEventListener("click", (event) => {
      event.stopPropagation();
    });
    checkboxCell.appendChild(checkbox);
    row.appendChild(checkboxCell);

    row.appendChild(createCell(profile.display_name || profile.name || profile.id || "Untitled"));
    row.appendChild(createCell(formatTimestamp(profile.createdAt)));
    const stagesCount = profile.configuration?.stages?.length || 0;
    const totalCycles = (profile.configuration?.stages || []).reduce(
      (total, stage) => total + (Number(stage.multiplier) || 1),
      0
    );
    const cyclesDisplay = stagesCount ? `${totalCycles}/${stagesCount}` : "--";
    row.appendChild(createCell(cyclesDisplay));

    const totalDuration = sumConfigurationDuration(profile.configuration || {});
    row.appendChild(createCell(formatDuration(totalDuration)));
    const volumeValue = profile.configuration?.volume;
    row.appendChild(createCell(volumeValue || volumeValue === 0 ? String(volumeValue) : "--"));

    const runCell = document.createElement("td");
    runCell.appendChild(createActionButton("Start", async () => {
      const profileId = profile.id || "";
      if (!profileId) {
        return;
      }
      try {
        await fetch("/profile/select", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile: profileId })
        });
        window.location.href = `/run?profile=${encodeURIComponent(profileId)}`;
      } catch (error) {
        console.error("Failed to select profile", error);
      }
    }));
    row.appendChild(runCell);

    const editCell = document.createElement("td");
    const idParam = encodeURIComponent(profile.id || "");
    editCell.appendChild(createActionLink("Edit", `/profiles/edit-form?id=${idParam}`));
    row.appendChild(editCell);

    row.addEventListener("click", (event) => {
      const target = event.target;
      if (target.closest("button, a, input, select, textarea, label")) {
        return;
      }
      checkbox.checked = !checkbox.checked;
      updateSelectAllState();
    });

    return row;
  };

  const updateSelectAllState = () => {
    if (!selectAllCheckbox) {
      return;
    }
    const checkboxes = Array.from(tableBody.querySelectorAll(".profile-checkbox"));
    if (!checkboxes.length) {
      selectAllCheckbox.checked = false;
      selectAllCheckbox.indeterminate = false;
      return;
    }
    const checkedCount = checkboxes.filter((box) => box.checked).length;
    selectAllCheckbox.checked = checkedCount === checkboxes.length;
    selectAllCheckbox.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
  };

  const loadProfiles = async () => {
    tableBody.innerHTML = "";
    try {
      const response = await fetch("/profiles");
      if (!response.ok) {
        throw new Error(`Failed to load profiles: ${response.status}`);
      }
      const profiles = await response.json();
      if (!profiles.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.className = "profiles-loading";
        cell.textContent = "No profiles found";
        cell.colSpan = 9;
        row.appendChild(cell);
        tableBody.appendChild(row);
        return;
      }
      profiles.forEach((profile) => {
        tableBody.appendChild(buildRow(profile));
      });
      updateSelectAllState();
    } catch (error) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.className = "profiles-loading";
      cell.textContent = "Unable to load profiles";
      cell.colSpan = 9;
      row.appendChild(cell);
      tableBody.appendChild(row);
      console.error(error);
    }
  };

  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener("change", () => {
      const checkboxes = tableBody.querySelectorAll(".profile-checkbox");
      checkboxes.forEach((checkbox) => {
        checkbox.checked = selectAllCheckbox.checked;
      });
      updateSelectAllState();
    });
  }

  if (deleteButton) {
    deleteButton.addEventListener("click", async () => {
      const selectedCheckboxes = Array.from(tableBody.querySelectorAll(".profile-checkbox"))
        .filter((checkbox) => checkbox.checked);
      const selectedIds = selectedCheckboxes
        .filter((checkbox) => checkbox.checked)
        .map((checkbox) => checkbox.dataset.profileId)
        .filter((id) => id);

      if (!selectedIds.length) {
        return;
      }

      const selectedNames = selectedCheckboxes
        .map((checkbox) => checkbox.dataset.profileName || "profile")
        .filter(Boolean);
      const nameList = selectedNames.length <= 3
        ? selectedNames.join(", ")
        : `${selectedNames.slice(0, 3).join(", ")} and ${selectedNames.length - 3} more`;
      const message = `Are you sure you want to delete ${selectedIds.length} profile${selectedIds.length === 1 ? "" : "s"}?\n${nameList}`;
      if (!window.confirm(message)) {
        return;
      }

      try {
        const response = await fetch("/profiles/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profiles: selectedIds })
        });

        if (!response.ok) {
          throw new Error(`Failed to delete profiles: ${response.status}`);
        }
        await loadProfiles();
      } catch (error) {
        console.error("Failed to delete profiles", error);
      }
    });
  }

  loadProfiles();

  tableBody.addEventListener("change", (event) => {
    if (event.target && event.target.classList.contains("profile-checkbox")) {
      updateSelectAllState();
    }
  });
})();
