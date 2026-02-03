const params = new URLSearchParams(window.location.search);
const profileId = params.get("id") || params.get("profile");
const profileName = params.get("name");
const viewMode = params.get("mode") === "view" || params.get("view") === "1";

const nameInput = document.getElementById("profile-name");
const chemistryInput = document.getElementById("profile-chemistry");
const volumeInput = document.getElementById("profile-volume");
const saveButton = document.getElementById("save-profile-button");
const saveStatus = document.getElementById("save-status");
const pageTitle = document.getElementById("profile-page-title");
const pageSubtitle = document.getElementById("profile-page-subtitle");

const stageSelect = document.getElementById("stage-select");
const stageNameInput = document.getElementById("stage-name");
const stageStepsContainer = document.getElementById("stage-steps");
const addStageButton = document.getElementById("add-stage");
const deleteStageButton = document.getElementById("delete-stage");
const addStepButton = document.getElementById("add-step");
const summaryList = document.getElementById("profile-summary-list");
const toggleReadViewButton = document.getElementById("toggle-read-view");
const editSections = document.querySelectorAll(".profile-edit");
const summarySection = document.getElementById("profile-summary");

let isReadView = viewMode;

const parseDuration = (value) => {
  if (typeof value !== "string") return 0;
  const parts = value.split(":").map((part) => Number(part));
  if (parts.length !== 3 || parts.some((part) => Number.isNaN(part))) {
    return 0;
  }
  return parts[0] * 3600 + parts[1] * 60 + parts[2];
};

const formatDuration = (seconds) => {
  const total = Math.max(0, Math.round(seconds || 0));
  const hrs = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return `${String(hrs).padStart(2, "0")}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
};

let idCounter = 0;
const generateId = (prefix) => {
  idCounter += 1;
  return `${prefix}-${Date.now()}-${idCounter}`;
};

const createStep = (overrides = {}) => ({
  id: generateId("step"),
  temperature: 20,
  duration: "00:00:30",
  cycles: 1,
  ...overrides
});

const createStage = (name) => ({
  id: generateId("stage"),
  name,
  steps: [createStep()]
});

let stages = [createStage("Stage 1")];
let selectedStageId = stages[0].id;

const getSelectedStage = () => stages.find((stage) => stage.id === selectedStageId);

const renderStageSelect = () => {
  if (!stageSelect) return;
  stageSelect.innerHTML = "";
  stages.forEach((stage) => {
    const option = document.createElement("option");
    option.value = stage.id;
    option.textContent = stage.name;
    stageSelect.appendChild(option);
  });
  stageSelect.value = selectedStageId;
};

const renderSteps = () => {
  if (!stageStepsContainer) return;
  const stage = getSelectedStage();
  stageStepsContainer.innerHTML = "";
  if (!stage) return;

  if (stageNameInput) {
    stageNameInput.value = stage.name;
  }

  stage.steps.forEach((step, index) => {
    const row = document.createElement("div");
    row.className = "profile-step-row";
    row.dataset.stepId = step.id;

    const tempField = document.createElement("div");
    tempField.className = "field";
    tempField.innerHTML = `
      <label for="temp-${step.id}">Step ${index + 1} Temperature (°C)</label>
      <input id="temp-${step.id}" type="number" value="${step.temperature}" />
    `;

    const durationField = document.createElement("div");
    durationField.className = "field";
    durationField.innerHTML = `
      <label for="duration-${step.id}">Step ${index + 1} Duration (HH:MM:SS)</label>
      <input id="duration-${step.id}" type="text" value="${step.duration}" />
    `;

    const cyclesField = document.createElement("div");
    cyclesField.className = "field";
    cyclesField.innerHTML = `
      <label for="cycles-${step.id}">Cycles</label>
      <input id="cycles-${step.id}" type="number" value="${step.cycles}" />
    `;

    const actions = document.createElement("div");
    actions.className = "step-actions";
    const deleteButton = document.createElement("button");
    deleteButton.className = "btn btn-secondary btn-small";
    deleteButton.type = "button";
    deleteButton.textContent = "Delete";
    deleteButton.addEventListener("click", () => {
      stage.steps = stage.steps.filter((item) => item.id !== step.id);
      if (stage.steps.length === 0) {
        stage.steps.push(createStep());
      }
      renderSteps();
    });
    actions.appendChild(deleteButton);

    row.appendChild(tempField);
    row.appendChild(durationField);
    row.appendChild(cyclesField);
    row.appendChild(actions);

    row.querySelector(`#temp-${step.id}`).addEventListener("input", (event) => {
      step.temperature = Number(event.target.value) || 0;
    });
    row.querySelector(`#duration-${step.id}`).addEventListener("input", (event) => {
      step.duration = event.target.value;
    });
    row.querySelector(`#cycles-${step.id}`).addEventListener("input", (event) => {
      step.cycles = Math.max(1, Number(event.target.value) || 1);
    });

    stageStepsContainer.appendChild(row);
  });

  renderSummary();
};

const renderSummary = () => {
  if (!summaryList) return;
  summaryList.innerHTML = "";
  stages.forEach((stage, stageIndex) => {
    const stageCard = document.createElement("div");
    stageCard.className = "profile-summary-stage";

    const stageHeader = document.createElement("div");
    stageHeader.className = "profile-summary-stage-header";
    stageHeader.textContent = `${stageIndex + 1}. ${stage.name}`;

    const stepsGrid = document.createElement("div");
    stepsGrid.className = "profile-summary-steps";

    stage.steps.forEach((step, stepIndex) => {
      const row = document.createElement("div");
      row.className = "profile-summary-step";
      row.innerHTML = `
        <div>
          <span class="profile-summary-label">Step</span>
          <span class="profile-summary-value">${stepIndex + 1}</span>
        </div>
        <div>
          <span class="profile-summary-label">Temp (°C)</span>
          <span class="profile-summary-value">${step.temperature}</span>
        </div>
        <div>
          <span class="profile-summary-label">Duration</span>
          <span class="profile-summary-value">${step.duration}</span>
        </div>
        <div>
          <span class="profile-summary-label">Cycles</span>
          <span class="profile-summary-value">${step.cycles}</span>
        </div>
      `;
      stepsGrid.appendChild(row);
    });

    stageCard.appendChild(stageHeader);
    stageCard.appendChild(stepsGrid);
    summaryList.appendChild(stageCard);
  });
};

const selectStage = (stageId) => {
  selectedStageId = stageId;
  renderStageSelect();
  renderSteps();
};

const addStage = () => {
  const newStage = createStage(`Stage ${stages.length + 1}`);
  stages.push(newStage);
  selectStage(newStage.id);
};

const deleteStage = () => {
  if (stages.length <= 1) return;
  stages = stages.filter((stage) => stage.id !== selectedStageId);
  selectedStageId = stages[0].id;
  renderStageSelect();
  renderSteps();
};

const addStep = () => {
  const stage = getSelectedStage();
  if (!stage) return;
  stage.steps.push(createStep());
  renderSteps();
};

const applyViewMode = () => {
  const editableSelectors = [
    "#profile-name",
    "#profile-volume",
    "#stage-select",
    "#stage-name",
    "#add-stage",
    "#delete-stage",
    "#add-step",
    "#save-profile-button",
    ".step-actions",
    ".stage-actions"
  ];
  if (isReadView) {
    editableSelectors.forEach((selector) => {
      document.querySelectorAll(selector).forEach((element) => {
        if (element.tagName === "INPUT" || element.tagName === "SELECT") {
          element.setAttribute("disabled", "disabled");
        } else {
          element.classList.add("is-hidden");
        }
      });
    });
    document.querySelectorAll(".profile-step-row input").forEach((input) => {
      input.setAttribute("disabled", "disabled");
    });
  } else {
    editableSelectors.forEach((selector) => {
      document.querySelectorAll(selector).forEach((element) => {
        if (element.tagName === "INPUT" || element.tagName === "SELECT") {
          element.removeAttribute("disabled");
        } else {
          element.classList.remove("is-hidden");
        }
      });
    });
    document.querySelectorAll(".profile-step-row input").forEach((input) => {
      input.removeAttribute("disabled");
    });
  }

  editSections.forEach((section) => {
    section.classList.toggle("is-hidden", isReadView);
  });
  if (summarySection) {
    summarySection.classList.toggle("is-hidden", !isReadView);
  }
  if (toggleReadViewButton) {
    toggleReadViewButton.textContent = isReadView ? "Edit View" : "Read View";
  }
  if (pageTitle) {
    pageTitle.textContent = isReadView ? "Profile Details" : "Edit Run Profile";
  }
  if (pageSubtitle) {
    pageSubtitle.textContent = isReadView
      ? "Read-only view of the selected profile."
      : "Update profile settings and steps.";
  }
};

const buildStepsPayload = () => {
  const payload = [];
  stages.forEach((stage) => {
    stage.steps.forEach((step) => {
      const durationSeconds = parseDuration(step.duration);
      const stepData = {
        setpoint: Number(step.temperature) || 0,
        duration: durationSeconds
      };
      if (step.cycles && Number(step.cycles) > 1) {
        payload.push({ repeat: [stepData], cycles: Number(step.cycles) });
      } else {
        payload.push(stepData);
      }
    });
  });
  return payload;
};

async function loadProfileDetails() {
  if (!profileId && !profileName) {
    renderStageSelect();
    renderSteps();
    return;
  }
  const query = profileId
    ? `id=${encodeURIComponent(profileId)}`
    : `name=${encodeURIComponent(profileName)}`;
  try {
    const response = await fetch(`/profiles/details?${query}`);
    if (!response.ok) {
      renderStageSelect();
      renderSteps();
      return;
    }
    const data = await response.json();
    if (data.title && nameInput) {
      nameInput.value = data.title;
    }
    if (data.chemistry && chemistryInput) {
      chemistryInput.value = data.chemistry;
    }
    if (data.volume && volumeInput) {
      volumeInput.value = data.volume;
    }

    const parsedStages = [];
    let stageIndex = 1;
    (data.steps || []).forEach((step) => {
      if (Array.isArray(step.repeat)) {
        const stage = {
          id: generateId("stage"),
          name: `Stage ${stageIndex}`,
          steps: step.repeat.map((repeatStep) => createStep({
            temperature: repeatStep.setpoint ?? 20,
            duration: formatDuration(repeatStep.duration ?? 0),
            cycles: Number(step.cycles) || 1
          }))
        };
        parsedStages.push(stage);
        stageIndex += 1;
      } else if (step.setpoint !== undefined) {
        parsedStages.push({
          id: generateId("stage"),
          name: `Stage ${stageIndex}`,
          steps: [createStep({
            temperature: step.setpoint ?? 20,
            duration: formatDuration(step.duration ?? 0),
            cycles: 1
          })]
        });
        stageIndex += 1;
      }
    });
    if (parsedStages.length) {
      stages = parsedStages;
      selectedStageId = stages[0].id;
    }
  } catch (err) {
    console.error("Failed to load profile details", err);
  }
  renderStageSelect();
  renderSteps();
  renderSummary();
  applyViewMode();
}

async function saveProfile() {
  if (!nameInput || !saveStatus) {
    return;
  }
  saveStatus.textContent = "Saving...";
  const payload = {
    name: nameInput.value.trim(),
    chemistry: chemistryInput ? chemistryInput.value : "",
    volume: volumeInput ? volumeInput.value : "",
    profile_id: profileId,
    steps: buildStepsPayload()
  };

  try {
    const response = await fetch("/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const error = await response.json();
      saveStatus.textContent = error.detail || "Failed to save";
      return;
    }
    saveStatus.textContent = "Saved";
    window.location.href = "/profiles-page";
  } catch (err) {
    saveStatus.textContent = "Failed to save";
    console.error("Save failed", err);
  }
}

if (stageSelect) {
  stageSelect.addEventListener("change", (event) => {
    selectStage(event.target.value);
  });
}

if (stageNameInput) {
  stageNameInput.addEventListener("input", (event) => {
    const stage = getSelectedStage();
    if (!stage) return;
    stage.name = event.target.value || stage.name;
    renderStageSelect();
  });
}

if (addStageButton) {
  addStageButton.addEventListener("click", addStage);
}

if (deleteStageButton) {
  deleteStageButton.addEventListener("click", deleteStage);
}

if (addStepButton) {
  addStepButton.addEventListener("click", addStep);
}

if (saveButton) {
  saveButton.addEventListener("click", saveProfile);
}

if (profileName && nameInput) {
  nameInput.value = profileName;
}

if (pageTitle && !profileId && !profileName) {
  pageTitle.textContent = "New Run Profile";
  if (pageSubtitle) {
    pageSubtitle.textContent = "Create a new profile and save it for future runs.";
  }
}

loadProfileDetails();

if (toggleReadViewButton) {
  toggleReadViewButton.addEventListener("click", () => {
    isReadView = !isReadView;
    renderSummary();
    applyViewMode();
  });
}
