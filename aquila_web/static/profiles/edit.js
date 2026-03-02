const params = new URLSearchParams(window.location.search);
const profileId = params.get("id") || params.get("profile");
const profileName = params.get("name");
const viewMode = params.get("mode") === "view" || params.get("view") === "1";

const nameInput = document.getElementById("profile-name");
const famLabelInput = document.getElementById("profile-fam-label");
const roxLabelInput = document.getElementById("profile-rox-label");
const saveButton = document.getElementById("save-profile-button");
const saveStatus = document.getElementById("save-status");
const pageTitle = document.getElementById("profile-page-title");
const pageSubtitle = document.getElementById("profile-page-subtitle");

const stageSelect = document.getElementById("stage-select");
const stageNameInput = document.getElementById("stage-name");
const stageCyclesInput = document.getElementById("stage-cycles");
const stageStepsContainer = document.getElementById("stage-steps");
const addStageButton = document.getElementById("add-stage");
const deleteStageButton = document.getElementById("delete-stage");
const addStepButton = document.getElementById("add-step");
const summaryList = document.getElementById("profile-summary-list");
const toggleReadViewButton = document.getElementById("toggle-read-view");
const editSections = document.querySelectorAll(".profile-edit");
const summarySection = document.getElementById("profile-summary");

let isReadView = viewMode;
if (isReadView && toggleReadViewButton) {
  isReadView = false;
}
const DEFAULT_DYE_LABELS = { fam: "FAM", rox: "ROX" };

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

const stepTypeOptions = [
  { value: "setpoint", label: "Temperature Hold" },
  { value: "ramp_rate", label: "Ramp Rate" },
  { value: "enable", label: "Enable" },
  { value: "disable", label: "Disable" },
  { value: "pcr_fanon", label: "PCR Fan On" },
  { value: "pcr_fanoff", label: "PCR Fan Off" }
];

const stepTypeLabel = (value) => {
  const match = stepTypeOptions.find((option) => option.value === value);
  return match ? match.label : "Step";
};

const createStep = (overrides = {}) => ({
  id: generateId("step"),
  type: "setpoint",
  temperature: 20,
  duration: "00:00:30",
  rampRate: 1,
  description: "",
  ...overrides
});

const createStage = (name, overrides = {}) => ({
  id: generateId("stage"),
  name,
  cycles: 1,
  steps: [createStep()],
  ...overrides
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
  if (stageCyclesInput) {
    stageCyclesInput.value = stage.cycles || 1;
  }

  stage.steps.forEach((step, index) => {
    const row = document.createElement("div");
    row.className = "profile-step-row";
    row.dataset.stepId = step.id;

    const typeField = document.createElement("div");
    typeField.className = "field";
    typeField.innerHTML = `
      <label for="type-${step.id}">Step ${index + 1} Type</label>
      <select id="type-${step.id}">
        ${stepTypeOptions
          .map(
            (option) =>
              `<option value="${option.value}">${option.label}</option>`
          )
          .join("")}
      </select>
    `;

    const tempField = document.createElement("div");
    tempField.className = "field";
    tempField.dataset.visibleFor = "setpoint";
    tempField.innerHTML = `
      <label for="temp-${step.id}">Step ${index + 1} Temperature (°C)</label>
      <input id="temp-${step.id}" type="number" value="${step.temperature}" />
    `;

    const durationField = document.createElement("div");
    durationField.className = "field";
    durationField.dataset.visibleFor = "setpoint,enable,disable";
    durationField.innerHTML = `
      <label for="duration-${step.id}">Step ${index + 1} Duration (HH:MM:SS)</label>
      <input id="duration-${step.id}" type="text" value="${step.duration}" />
    `;

    const rampRateField = document.createElement("div");
    rampRateField.className = "field";
    rampRateField.dataset.visibleFor = "ramp_rate";
    rampRateField.innerHTML = `
      <label for="ramp-${step.id}">Ramp Rate (°C/s)</label>
      <input id="ramp-${step.id}" type="text" inputmode="decimal" value="${step.rampRate}" />
    `;

    const descriptionField = document.createElement("div");
    descriptionField.className = "field";
    descriptionField.dataset.visibleFor = "setpoint,ramp_rate,enable,disable,pcr_fanon,pcr_fanoff";
    descriptionField.innerHTML = `
      <label for="desc-${step.id}">Description</label>
      <input id="desc-${step.id}" type="text" value="${step.description}" />
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

    row.appendChild(typeField);
    row.appendChild(tempField);
    row.appendChild(durationField);
    row.appendChild(rampRateField);
    row.appendChild(descriptionField);
    row.appendChild(actions);

    const updateStepVisibility = () => {
      row.querySelectorAll("[data-visible-for]").forEach((field) => {
        const types = field.dataset.visibleFor.split(",");
        field.style.display = types.includes(step.type) ? "" : "none";
      });
    };

    row.querySelector(`#type-${step.id}`).value = step.type;
    row.querySelector(`#type-${step.id}`).addEventListener("change", (event) => {
      step.type = event.target.value;
      updateStepVisibility();
      renderSummary();
    });
    row.querySelector(`#temp-${step.id}`).addEventListener("input", (event) => {
      step.temperature = Number(event.target.value) || 0;
    });
    row.querySelector(`#duration-${step.id}`).addEventListener("input", (event) => {
      step.duration = event.target.value;
    });
    row.querySelector(`#ramp-${step.id}`).addEventListener("input", (event) => {
      step.rampRate = Number(event.target.value) || 0;
    });
    row.querySelector(`#desc-${step.id}`).addEventListener("input", (event) => {
      step.description = event.target.value;
    });

    updateStepVisibility();

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
      const summaryItems = [
        {
          label: "Step",
          value: stepIndex + 1
        },
        {
          label: "Type",
          value: stepTypeLabel(step.type)
        }
      ];

      if (step.type === "setpoint") {
        summaryItems.push(
          { label: "Temp (°C)", value: step.temperature },
          { label: "Duration", value: step.duration }
        );
      }

      if (step.type === "ramp_rate") {
        summaryItems.push({ label: "Ramp Rate", value: step.rampRate });
      }

      if (step.type === "enable" || step.type === "disable") {
        summaryItems.push({ label: "Duration", value: step.duration });
      }

      if (step.description) {
        summaryItems.push({ label: "Description", value: step.description });
      }

      row.innerHTML = summaryItems
        .map(
          (item) => `
        <div>
          <span class="profile-summary-label">${item.label}</span>
          <span class="profile-summary-value">${item.value}</span>
        </div>
      `
        )
        .join("");
      stepsGrid.appendChild(row);
    });

    stageCard.appendChild(stageHeader);
    if (stage.cycles && stage.cycles > 1) {
      const stageCycles = document.createElement("div");
      stageCycles.className = "profile-summary-stage-header";
      stageCycles.textContent = `Cycles: ${stage.cycles}`;
      stageCard.appendChild(stageCycles);
    }
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
    "#profile-fam-label",
    "#profile-rox-label",
    "#stage-select",
    "#stage-name",
    "#stage-cycles",
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
    document.querySelectorAll(".profile-step-row input, .profile-step-row select").forEach((input) => {
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
    document.querySelectorAll(".profile-step-row input, .profile-step-row select").forEach((input) => {
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
    const stepsPayload = stage.steps
      .map((step) => {
        const durationSeconds = parseDuration(step.duration);
        if (step.type === "setpoint") {
          const stepData = {
            setpoint: Number(step.temperature) || 0,
            duration: durationSeconds
          };
          if (step.description) {
            stepData.description = step.description;
          }
          return stepData;
        }
        if (step.type === "ramp_rate") {
          const stepData = { ramp_rate: Number(step.rampRate) || 0 };
          if (step.description) {
            stepData.description = step.description;
          }
          return stepData;
        }
        if (step.type === "enable" || step.type === "disable") {
          const stepData = {
            [step.type]: 0,
            duration: durationSeconds
          };
          if (step.description) {
            stepData.description = step.description;
          }
          return stepData;
        }
        if (step.type === "pcr_fanon" || step.type === "pcr_fanoff") {
          const stepData = { [step.type]: step.type === "pcr_fanon" ? 1 : 0 };
          if (step.description) {
            stepData.description = step.description;
          }
          return stepData;
        }
        return null;
      })
      .filter(Boolean);

    const stageCycles = Math.max(1, Number(stage.cycles) || 1);
    if (stageCycles > 1 && stepsPayload.length) {
      payload.push({ repeat: stepsPayload, cycles: stageCycles });
    } else {
      payload.push(...stepsPayload);
    }
  });
  return payload;
};

const parseProfileStep = (step) => {
  if (step.setpoint !== undefined) {
    return createStep({
      type: "setpoint",
      temperature: step.setpoint ?? 20,
      duration: formatDuration(step.duration ?? 0),
      description: step.description || ""
    });
  }
  if (step.ramp_rate !== undefined) {
    return createStep({
      type: "ramp_rate",
      rampRate: step.ramp_rate ?? 1,
      description: step.description || ""
    });
  }
  if (step.enable !== undefined) {
    return createStep({
      type: "enable",
      duration: formatDuration(step.duration ?? 0),
      description: step.description || ""
    });
  }
  if (step.disable !== undefined) {
    return createStep({
      type: "disable",
      duration: formatDuration(step.duration ?? 0),
      description: step.description || ""
    });
  }
  if (step.pcr_fanon !== undefined) {
    return createStep({
      type: "pcr_fanon",
      description: step.description || ""
    });
  }
  if (step.pcr_fanoff !== undefined) {
    return createStep({
      type: "pcr_fanoff",
      description: step.description || ""
    });
  }
  return null;
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
  if (famLabelInput) {
    famLabelInput.value = data.labels?.fam || DEFAULT_DYE_LABELS.fam;
  }
  if (roxLabelInput) {
    roxLabelInput.value = data.labels?.rox || DEFAULT_DYE_LABELS.rox;
  }

    const parsedStages = [];
    let stageIndex = 1;
    (data.steps || []).forEach((step) => {
      if (Array.isArray(step.repeat)) {
        const stageSteps = step.repeat
          .map((repeatStep) => parseProfileStep(repeatStep))
          .filter(Boolean);
        parsedStages.push(createStage(`Stage ${stageIndex}`, {
          cycles: Math.max(1, Number(step.cycles) || 1),
          steps: stageSteps.length ? stageSteps : [createStep()]
        }));
        stageIndex += 1;
        return;
      }
      const parsedStep = parseProfileStep(step);
      if (parsedStep) {
        parsedStages.push(createStage(`Stage ${stageIndex}`, {
          cycles: 1,
          steps: [parsedStep]
        }));
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
    profile_id: profileId,
    steps: buildStepsPayload(),
    fam_label: famLabelInput ? famLabelInput.value.trim() : DEFAULT_DYE_LABELS.fam,
    rox_label: roxLabelInput ? roxLabelInput.value.trim() : DEFAULT_DYE_LABELS.rox
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

if (stageCyclesInput) {
  stageCyclesInput.addEventListener("input", (event) => {
    const stage = getSelectedStage();
    if (!stage) return;
    stage.cycles = Math.max(1, Number(event.target.value) || 1);
    renderSummary();
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

if (famLabelInput) {
  famLabelInput.value = DEFAULT_DYE_LABELS.fam;
}

if (roxLabelInput) {
  roxLabelInput.value = DEFAULT_DYE_LABELS.rox;
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
