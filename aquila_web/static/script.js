const titleEl = document.querySelector("#panel h1");
const textEl = document.querySelector("#panel p");
//const timerEl = document.querySelector("#timer");
const timerEl = document.getElementById("timer");

let seconds = 0;
let currentScreen = null;

// Display a panel object { title: "...", text: "..." }
function showPanel(panel) {
  titleEl.textContent = panel.title;
  textEl.textContent = panel.text;
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
        let targetPath = window.location.pathname;

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
    const select = document.getElementById("myselect");
    let profile = null;

    if (select && select.value){
        profile = select.value;
    }

    try {
        const ret = await fetch("/button/run", {
            method:"POST"
        });
        console.log("Run button clicked", await ret.text());
    } catch (err) {
        console.error("Button failed", err);
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

async function loadResultsTable(){
    const table = document.getElementById("results-table");
    if(!table){
        console.log("No table");
        return;
    }

    let data = {};
    try {
        const ret = await fetch("/results");
        if (ret.ok){
            data = await ret.json();
            console.log("results json raw", data)
        } else {
            console.error("Failed to retrieve results" , ret.status);
        }
    } catch (err){
        console.error("Error fetching results" , err );
    }

    table.innerHTML = "";

    const numRows = 3;
    const numCols = 5;
    const rowHeader = [ "","ROX", "FAM"];
    const colHeader = [ "","Tube 1", "Tube 2", "Tube 3" , "Tube 4"];

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

                const value = 
                    data[rowKey] && data[rowKey][colKey]
                    ? data[rowKey][colKey]
                    : "Not Detected";

                cell.textContent = value;
            }

            tr.appendChild(cell);
        }
        table.appendChild(tr);
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
            opt.textContent = "No profiles fouind";
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
            opt.textContent = p.label;
            select.appendChild(opt);

        });

        select.addEventListener("change", async () => {
            const profile = select.value;
            console.log("Dropdown changed, profile =", profile);
            try {
                await fetch("/profile/select",{
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({profile})
                });
            } catch (err) {
                console.error("Failed to send selected profile:" , err);
            }
        });

    } catch (err) {
        console.error("Error loading profiles:" , err);
    }
}


document.addEventListener("DOMContentLoaded", () => {
    if (typeof loadProfiles === "function") {
        loadProfiles();
    }
    if (typeof loadResultsTable === "function") {
        loadResultsTable();
    }
});




