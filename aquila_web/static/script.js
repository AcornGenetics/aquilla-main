const titleEl = document.querySelector("#panel h1");
const textEl = document.querySelector("#panel p");
const statusTitleEl = document.getElementById("status-title");
const statusTextEl = document.getElementById("status-text");
//const timerEl = document.querySelector("#timer");
const timerEl = document.getElementById("timer");
const runButton = document.getElementById("run-cta");
const runCompleteModal = document.getElementById("run-complete-modal");
const runModalClose = runCompleteModal
  ? runCompleteModal.querySelector(".run-modal__close")
  : null;
if (runCompleteModal) {
  const modalReset = runCompleteModal.querySelector(".run-modal__reset");
  if (modalReset) {
    modalReset.remove();
  }
}
const runResetButton = document.getElementById("run-reset-button");
const drawerActions = document.getElementById("drawer-actions");
const devOpticsPath = document.getElementById("dev-optics-path");
const devOpticsWrapper = document.getElementById("run-optics-tab");
const runNameInput = document.getElementById("run-name-input");
const runWarning = document.getElementById("run-warning");
const drawerWarning = document.getElementById("drawer-warning");

let seconds = 0;
let currentScreen = null;
let runDoneAcknowledged = false;
let lastDrawerState = { open: null, closed: null };
let lastScreen = null;
let completedRunSeen = false;
let resultsRequestId = 0;
const RUN_ACK_KEY = "runCompleteAcknowledged";
const TUBE_NAME_KEY = "aqTubeNames";
const DEFAULT_TUBE_NAMES = ["Tube 1", "Tube 2", "Tube 3", "Tube 4"];
let tubeNames = DEFAULT_TUBE_NAMES.slice();
const DEFAULT_DYE_LABELS = { fam: "FAM", rox: "ROX" };
let dyeLabels = { ...DEFAULT_DYE_LABELS };

const loadTubeNames = () => {
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

const saveTubeNames = (names) => {
  tubeNames = names.map((name, index) => {
    const fallback = DEFAULT_TUBE_NAMES[index];
    return typeof name === "string" && name.trim() ? name.trim() : fallback;
  });
  try {
    localStorage.setItem(TUBE_NAME_KEY, JSON.stringify(tubeNames));
  } catch (error) {
    return;
  }
};

const updateTubeLabels = () => {
  const labelInputs = document.querySelectorAll(".results-tube__label-input");
  labelInputs.forEach((input, index) => {
    input.value = tubeNames[index] || DEFAULT_TUBE_NAMES[index];
  });
};

const setupTubeNameInputs = () => {
  const labelInputs = document.querySelectorAll(".results-tube__label-input");
  if (!labelInputs.length) {
    return;
  }
  labelInputs.forEach((input, index) => {
    input.value = tubeNames[index] || DEFAULT_TUBE_NAMES[index];
    input.addEventListener("input", (event) => {
      const nextNames = tubeNames.slice();
      nextNames[index] = event.target.value;
      saveTubeNames(nextNames);
      if (typeof loadResults === "function") {
        loadResults();
      }
    });
  });
};

const applyDyeLabels = (labels = {}) => {
  dyeLabels = {
    fam: labels.fam || DEFAULT_DYE_LABELS.fam,
    rox: labels.rox || DEFAULT_DYE_LABELS.rox
  };
  if (typeof loadResults === "function") {
    loadResults();
  }
};

const loadProfileLabels = async (profileId) => {
  if (!profileId) {
    applyDyeLabels();
    return;
  }
  try {
    const response = await fetch(`/profiles/details?id=${encodeURIComponent(profileId)}`);
    if (!response.ok) {
      applyDyeLabels();
      return;
    }
    const data = await response.json();
    applyDyeLabels(data.labels || {});
  } catch (error) {
    applyDyeLabels();
  }
};

// Display a panel object { title: "...", text: "..." }
function showPanel(panel) {
  if (isDashboard && statusTitleEl && statusTextEl) {
    statusTitleEl.textContent = panel.title;
    statusTextEl.textContent = panel.text;
    return;
  }
  if (titleEl && textEl) {
    titleEl.textContent = panel.title;
    textEl.textContent = panel.text;
  }
}

function formatElapsed(seconds) {
  
  if( typeof seconds !== "number" || isNaN(seconds)) {
    return;
  }

  const mins = Math.floor(seconds / 60);
  const secs = (seconds % 60);
  console.log(`Min:${mins}, sec: ${secs}`)
  const formatted = `${mins}:${secs.toString().padStart(2,'0')}`;
  //timerEl.textContent = `${mins}:${secs}`;
  if (timerEl){
   timerEl.textContent = formatted;
  }
}

setInterval(() => {
  seconds++;
  formatElapsed();
}, 1000);


const readySection = document.getElementById("ready-section");
const runningSection = document.getElementById("running-section");
const completeSection = document.getElementById("complete-section");
const normalizedPath = window.location.pathname.replace(/\/$/, "");
const isDashboard = normalizedPath === "/run" || Boolean(readySection);

function updateDashboardSections(screen) {
  if (!isDashboard) {
    return false;
  }

  if (!screen) {
    return false;
  }

  if (screen === "init") {
    screen = "ready";
  }

  const allowedScreens = new Set(["ready", "running", "complete"]);
  if (!allowedScreens.has(screen)) {
    return false;
  }

  currentScreen = screen;

  const sections = [
    { key: "ready", element: readySection },
    { key: "running", element: runningSection }
  ];

  sections.forEach(({ key, element }) => {
    if (!element) {
      return;
    }
    const shouldShow = key === "running" ? screen === "running" : screen !== "running";
    if (shouldShow) {
      element.classList.remove("is-hidden");
    } else {
      element.classList.add("is-hidden");
    }
  });

  setRunResetVisibility(true);

  return true;
}

function setRunButtonState(isRunning) {
  if (!runButton) {
    return;
  }
  runButton.disabled = isRunning;
  if (isRunning) {
    runButton.classList.add("run-cta--disabled");
  } else {
    runButton.classList.remove("run-cta--disabled");
  }
  if (runNameInput) {
    runNameInput.disabled = isRunning;
  }
}

function resetResultsUI(message = "Run for results!") {
  resultsRequestId += 1;
  const summaryEl = document.getElementById("results-summary");
  const tubeEls = document.querySelectorAll(".results-tube");
  if (summaryEl) {
    summaryEl.textContent = message;
    summaryEl.classList.toggle("is-error", message === "Results unavailable");
  }
  tubeEls.forEach((tubeEl) => {
    const dot = tubeEl.querySelector(".results-dot");
    if (dot) {
      dot.classList.remove("is-detected");
      dot.classList.remove("is-inconclusive");
      dot.classList.remove("is-not-detected");
    }
  });
}

function setRunWarning(message) {
  if (!runWarning) {
    return;
  }
  if (message) {
    runWarning.textContent = message;
    runWarning.classList.remove("is-hidden");
  } else {
    runWarning.textContent = "";
    runWarning.classList.add("is-hidden");
  }
}

function setDrawerWarning(message) {
  if (!drawerWarning) {
    return;
  }
  if (message) {
    drawerWarning.textContent = message;
    drawerWarning.classList.remove("is-hidden");
  } else {
    drawerWarning.textContent = "";
    drawerWarning.classList.add("is-hidden");
  }
}

function setDrawerActionsVisibility(isVisible) {
  if (!drawerActions) {
    return;
  }
  drawerActions.classList.toggle("is-hidden", !isVisible);
}

function setRunResetVisibility(isVisible) {
  if (!runResetButton) {
    return;
  }
  runResetButton.classList.toggle("is-hidden", !isVisible);
}

function setOpticsVisibility(isDev) {
  if (!devOpticsWrapper) {
    return;
  }
  devOpticsWrapper.classList.toggle("is-hidden", !isDev);
}

function updateDrawerWarningFromState(state) {
  if (!state) {
    return;
  }
  lastDrawerState = {
    open: Boolean(state.open),
    closed: Boolean(state.closed)
  };
  if (lastDrawerState.open && !lastDrawerState.closed) {
    setDrawerWarning("Drawer is open");
  } else {
    setDrawerWarning("");
  }
}

function showRunCompleteModal() {
  if (!runCompleteModal) {
    return;
  }
  if (runDoneAcknowledged) {
    return;
  }
  runCompleteModal.classList.remove("is-hidden");
}

function hideRunCompleteModal() {
  if (!runCompleteModal) {
    return;
  }
  runDoneAcknowledged = true;
  try {
    window.sessionStorage.setItem(RUN_ACK_KEY, "true");
  } catch (error) {
    console.warn("Failed to persist run ack", error);
  }
  runCompleteModal.classList.add("is-hidden");
  if (isDashboard) {
    setRunWarning("");
  }
  acknowledgeRunComplete();
}

function resetRunScreen() {
  if (runCompleteModal) {
    runCompleteModal.classList.add("is-hidden");
  }
  runDoneAcknowledged = true;
  completedRunSeen = false;
  resultsRequestId += 1;
  try {
    window.sessionStorage.removeItem(RUN_ACK_KEY);
  } catch (error) {
    console.warn("Failed to clear run ack", error);
  }
  if (isDashboard) {
    setRunWarning("");
    setDrawerActionsVisibility(true);
    updateDashboardSections("ready");
    resetResultsUI();
  }
  fetch("/results/clear", { method: "POST" }).catch(() => null);
  acknowledgeRunComplete();
}

function acknowledgeRunComplete() {
  if (!isDashboard) {
    return;
  }
  fetch("/run/complete/ack", { method: "POST" }).catch(() => null);
}

// Connect to WebSocket backend
const host = window.location.host;
const wsUrl = `ws://${host}/ws`;
const socket = new WebSocket( wsUrl ); // adjust URL if needed

socket.onmessage = function(event) {
  try {
    const panel = JSON.parse(event.data);
    console.log("Elapsed secs:", panel.elapsed);
    showPanel(panel);
    if("elapsed" in panel){
      formatElapsed(panel.elapsed);
    }
    if (panel.screen){
        const screen = panel.screen;
        const previousScreen = lastScreen;
        lastScreen = screen;
        if (screen === "running") {
          completedRunSeen = false;
          runDoneAcknowledged = false;
          try {
            window.sessionStorage.removeItem(RUN_ACK_KEY);
          } catch (error) {
            console.warn("Failed to clear run ack", error);
          }
        }
        if (screen === "running") {
          setRunButtonState(true);
          resetResultsUI("Results pending");
          setRunWarning("");
          runDoneAcknowledged = false;
        } else if (screen === "ready" || screen === "complete") {
          setRunButtonState(false);
          if (screen === "ready" && previousScreen === "running" && !runDoneAcknowledged) {
            resetResultsUI("Results unavailable");
          }
        }
        if (screen === "complete" && !runDoneAcknowledged) {
          showRunCompleteModal();
          loadRunName();
          loadResults();
          completedRunSeen = true;
        }
        if (isDashboard) {
          setDrawerActionsVisibility(screen !== "running");
        }
        let targetPath = window.location.pathname;

        currentScreen = screen;

        if (isDashboard) {
            updateDashboardSections(screen);
            return;
        }

        if (screen === "init"){
            targetPath = "/";
            console.log("INIT PATH", targetPath);
        } else if (screen === "ready"){
            targetPath = "/ready";
            console.log("READY PATH", targetPath);
        } else if (screen === "running"){
            targetPath = "/run";
            console.log("RUN PATH", targetPath);
        } else if (screen === "complete"){
            targetPath = "/complete";
            console.log("COMPLETE PATH", targetPath);
        }
        
        if (targetPath !== window.location.pathname){
            currentScreen = screen;
            window.location.href = targetPath;
            console.log("href" , window.location.href)
            return;
        }
    }
    if (panel.drawer_state_open !== undefined || panel.drawer_state_closed !== undefined) {
      updateDrawerWarningFromState({
        open: panel.drawer_state_open,
        closed: panel.drawer_state_closed
      });
    }
  } catch (e) {
    console.error("Invalid panel data", e);
  }
};

socket.onopen = function() {
  console.log("WebSocket connection established.");
};

socket.onerror = function(error) {
  console.error("WebSocket error:", error);
};

socket.onclose = function() {
  console.warn("WebSocket connection closed.");
};

async function notifyRun(){
    if (runButton && runButton.disabled) {
        return;
    }
    resetResultsUI();
    const select = document.getElementById("mySelect");
    let profile = null;

    if (select && select.value){
        profile = select.value;
    }

    if (!profile) {
        setRunWarning("Select a profile before running.");
        return;
    }

    if (runNameInput && !runNameInput.value.trim()) {
        setRunWarning("Enter a run name before running.");
        return;
    }

    if (lastDrawerState.open && !lastDrawerState.closed) {
        setRunWarning("Close the drawer before running.");
        return;
    }

    setRunWarning("");

    try {
        const ret = await fetch("/button/run", {
            method:"POST"
        });
        if (ret.ok) {
          const payload = await ret.json();
          if (payload && payload.ok === false) {
            setRunButtonState(false);
            if (payload.message) {
              setRunWarning(payload.message);
            }
          }
        }
        console.log("Run button clicked", await ret.text());
    } catch (err) {
        console.error("Button failed", err);
    }
}

async function loadRunName() {
  if (!runNameInput) {
    return;
  }
  try {
    const response = await fetch("/run/name");
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    if (data && data.name) {
      runNameInput.value = data.name;
    }
  } catch (error) {
    console.error("Failed to load run name", error);
  }
}

async function saveRunName() {
  if (!runNameInput) {
    return;
  }
  const name = runNameInput.value.trim();
  try {
    const response = await fetch("/run/name", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name })
    });
    if (response.ok) {
      const data = await response.json();
      if (data && data.name) {
        runNameInput.value = data.name;
      }
    }
  } catch (error) {
    console.error("Failed to save run name", error);
  }
}

async function notifyDrawerOpen(){
    try {
        const ret = await fetch("/button/open", {
            method:"POST"
        });
        console.log("Drawer open clicked", await ret.text());
    } catch (err) {
        console.error("Button failed", err);
    }
}

async function notifyDrawerClose(){
    try {
        const ret = await fetch("/button/close", {
            method:"POST"
        });
        console.log("Drawer close clicked", await ret.text());
    } catch (err) {
        console.error("Button failed", err);
    }
}

async function notifyExit(){
    try {
        const ret = await fetch("/button/exit", {
            method:"POST"
        });
        console.log("Exit button clicked", await ret.text());
    } catch (err) {
        console.error("Button failed", err);
    }
}

async function loadResults(){
    const requestId = ++resultsRequestId;
    const table = document.getElementById("results-table");
    const summaryEl = document.getElementById("results-summary");
    const tubeEls = document.querySelectorAll(".results-tube");
    if(!table && !summaryEl && tubeEls.length === 0){
        console.log("No results UI");
        return;
    }
    if (normalizedPath === "/run" && currentScreen !== "complete") {
        const pending = currentScreen === "running";
        resetResultsUI(pending ? "Results pending" : "Run for results!");
        return;
    }

    try {
        const statusResponse = await fetch("/results/status");
        if (statusResponse.ok) {
            const statusData = await statusResponse.json();
            if (statusData && statusData.cleared) {
                resetResultsUI("Run for results!");
                return;
            }
        }
    } catch (err) {
        console.error("Error fetching results status", err);
    }

    let data = {};
    let hasResultsPayload = false;
    try {
        const ret = await fetch("/results");
        if (ret.ok){
            data = await ret.json();
            if (requestId !== resultsRequestId) {
                return;
            }
            console.log("results json raw", data)
            if (data && typeof data === "object") {
                if (data.path || data.results_path) {
                    hasResultsPayload = Boolean(data.path || data.results_path);
                } else if (!data.data) {
                    hasResultsPayload = Object.keys(data).length > 0;
                }
            }
        } else {
            console.error("Failed to retrieve results" , ret.status);
        }
    } catch (err){
        console.error("Error fetching results" , err );
        if (requestId !== resultsRequestId) {
            return;
        }
    }

    const hasErrorPayload = data && typeof data === "object" && data.data && data.data.failed;
    const hasResults = hasResultsPayload && !hasErrorPayload;

    if (requestId !== resultsRequestId) {
        return;
    }

    if (table) {
        table.innerHTML = "";

        const numRows = 3;
        const numCols = 5;
        const rowHeader = ["", dyeLabels.rox, dyeLabels.fam];
        const colHeader = ["", ...tubeNames];

        for(let r = 0; r < numRows; r++){
            const tr = document.createElement("tr");

            for(let c = 0; c < numCols; c++){
                const isHeader = r === 0 || c === 0;
                const cell = document.createElement(isHeader ? "th" : "td");
                
                if(r === 0 && c === 0){
                    cell.textContent = "";
                } else if (r === 0) {
                    cell.textContent = colHeader[c] || "";
                } else if (c === 0) {
                    cell.textContent = rowHeader[r] || "";
                } else {
                    const rowKey = String(r);
                    const colKey = String(c);

                    const value = hasResults && data[rowKey] && data[rowKey][colKey]
                        ? data[rowKey][colKey]
                        : "";

                    cell.textContent = value;
                }

                tr.appendChild(cell);
            }
            table.appendChild(tr);
        }
    }

    if (summaryEl || tubeEls.length) {
        if (!hasResults) {
            if (summaryEl) {
                const errorMessage = hasErrorPayload ? "Error in results path" : "Run for results!";
                summaryEl.textContent = errorMessage;
                summaryEl.classList.toggle("is-error", hasErrorPayload);
            }
            tubeEls.forEach((tubeEl) => {
                const dot = tubeEl.querySelector(".results-dot");
                if (!dot) {
                    return;
                }
                dot.classList.remove("is-detected");
                dot.classList.remove("is-inconclusive");
                dot.classList.remove("is-not-detected");
            });
            return;
        }
        const tubeDetected = Array(4).fill(false);
        const tubeInconclusive = Array(4).fill(false);
        Object.values(data || {}).forEach((row) => {
            if (!row || typeof row !== "object") {
                return;
            }
            for (let col = 1; col <= 4; col += 1) {
                const value = row[String(col)];
                if (value === "Inconclusive") {
                    tubeInconclusive[col - 1] = true;
                    tubeDetected[col - 1] = false;
                } else if (value && value !== "Not Detected") {
                    if (!tubeInconclusive[col - 1]) {
                        tubeDetected[col - 1] = true;
                    }
                }
            }
        });

        if (summaryEl) {
            const detectedLabels = tubeDetected
              .map((detected, index) => (detected ? tubeNames[index] : null))
              .filter(Boolean);
            const inconclusiveLabels = tubeInconclusive
              .map((flag, index) => (flag ? `${tubeNames[index]} inconclusive` : null))
              .filter(Boolean);
            if (!detectedLabels.length && !inconclusiveLabels.length) {
                summaryEl.textContent = "No targets detected";
            } else {
                const parts = [];
                if (detectedLabels.length) {
                    parts.push(`Detected: ${detectedLabels.join(", ")}`);
                }
                if (inconclusiveLabels.length) {
                    parts.push(inconclusiveLabels.join(", "));
                }
                summaryEl.textContent = parts.join(" · ");
            }
        }

        tubeEls.forEach((tubeEl, index) => {
            const dot = tubeEl.querySelector(".results-dot");
            if (!dot) {
                return;
            }
            if (tubeInconclusive[index]) {
                dot.classList.add("is-inconclusive");
                dot.classList.remove("is-detected");
                dot.classList.remove("is-not-detected");
            } else if (tubeDetected[index]) {
                dot.classList.add("is-detected");
                dot.classList.remove("is-inconclusive");
                dot.classList.remove("is-not-detected");
            } else {
                dot.classList.remove("is-detected");
                dot.classList.remove("is-inconclusive");
                dot.classList.add("is-not-detected");
            }
        });
    }
}

async function loadProfiles(){
    const select = document.getElementById("mySelect");
    if (!select){
        return;
    }

    try{
        const ret = await fetch("/profiles");
        console.log("profile status", ret.status);
        if(!ret.ok){
            console.error("Failed to fetch profiles", ret.status);
            return;
        }

        const profiles = await ret.json();
        console.log("Profiles:", profiles);

        select.innerHTML = "";

        if(profiles.length === 0){
            const opt = document.createElement("option");
            opt.value = "";
            opt.textContent = "No profiles found";
            select.appendChild(opt);
            return;
        }

        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "Select a profile";
        placeholder.disabled = true;
        placeholder.selected = true;
        select.appendChild(placeholder);

        profiles.forEach(p => {
            const opt = document.createElement("option");
            opt.value = p.id;
            opt.textContent = p.name || p.label || p.id;
            select.appendChild(opt);

        });

        const selectProfile = (profileValue) => {
            const matchedOption = Array.from(select.options).find(option => (
                option.value === profileValue || option.textContent === profileValue
            ));
            if (!matchedOption) {
                return false;
            }
            select.value = matchedOption.value;
            matchedOption.selected = true;
            select.selectedIndex = Array.from(select.options).indexOf(matchedOption);
            const placeholderOption = select.querySelector("option[disabled]");
            if (placeholderOption) {
                placeholderOption.selected = false;
            }
            loadProfileLabels(matchedOption.value);
            return true;
        };

        const requestedProfile = new URLSearchParams(window.location.search).get("profile");
        if (requestedProfile) {
            const matched = selectProfile(requestedProfile);
            if (matched) {
                try {
                    await fetch("/profile/select", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ profile: requestedProfile })
                    });
                } catch (err) {
                    console.error("Failed to sync selected profile:" , err);
                }
            }
        }

        if (!requestedProfile) {
            try {
                const statusResp = await fetch("/button_status");
                if (statusResp.ok) {
                    const status = await statusResp.json();
                    if (status.profile) {
                        selectProfile(status.profile);
                    }
                }
            } catch (err) {
                console.error("Failed to load selected profile:" , err);
            }
        }

        select.addEventListener("change", async () => {
            const profile = select.value;
            console.log("Dropdown changed, profile =", profile);
            setRunWarning("");
            try {
                await fetch("/profile/select",{
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({profile})
                });
                loadProfileLabels(profile);
            } catch (err) {
                console.error("Failed to send selected profile:" , err);
            }
        });

    } catch (err) {
        console.error("Error loading profiles:" , err);
    }
}


document.addEventListener("DOMContentLoaded", () => {
    tubeNames = loadTubeNames();
    updateTubeLabels();
    setupTubeNameInputs();
    applyDyeLabels();
    try {
        runDoneAcknowledged = window.sessionStorage.getItem(RUN_ACK_KEY) === "true";
    } catch (error) {
        runDoneAcknowledged = false;
    }
    completedRunSeen = false;
    loadRunName();
    if (runNameInput) {
        runNameInput.addEventListener("blur", saveRunName);
    }
    fetch("/button_status")
      .then((response) => response.ok ? response.json() : null)
      .then((status) => {
        const isDev = Boolean(status && status.dev_simulate);
        setOpticsVisibility(isDev);
        if (isDev && devOpticsPath) {
            fetch("/dev/optics_path")
              .then((response) => response.ok ? response.json() : null)
              .then((data) => {
                if (data && data.path) {
                  devOpticsPath.value = data.path;
                }
              })
              .catch(() => null);
            devOpticsPath.addEventListener("blur", async () => {
                const path = devOpticsPath.value.trim();
                try {
                    await fetch("/dev/optics_path", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ path })
                    });
                } catch (error) {
                    console.error("Failed to save optics path", error);
                }
            });
        }
      })
      .catch(() => {
        setOpticsVisibility(false);
      });
    if (runModalClose) {
        runModalClose.addEventListener("click", hideRunCompleteModal);
    }
    if (runResetButton) {
        runResetButton.addEventListener("click", resetRunScreen);
    }
    if (typeof loadProfiles === "function") {
        loadProfiles();
    }
    if (typeof loadResults === "function") {
        loadResults();
    }
    if (isDashboard) {
        setDrawerActionsVisibility(currentScreen !== "running");
    }
    if (normalizedPath === "/run") {
        updateDrawerWarningFromState(lastDrawerState);
    }
    if (isDashboard) {
        setRunResetVisibility(true);
    }
});

window.addEventListener("beforeunload", () => {
    return;
});




