// Structured profile builder (issue #200, Structured Profiles B1).
// The markup lives in builder.html; this script wires behavior: Stage enable
// toggles (grey/disable while preserving values) and save. Field validation is
// B3; Amplification Sub-stage add/remove is B2.
(function () {
  "use strict";

  // Stages with an enable checkbox. Amplification is always present (no toggle).
  var OPTIONAL_STAGES = ["incubation", "denaturation", "finalhold"];

  function valueInputs(card) {
    // Every editable value field in the card (temp/time) — never the checkbox.
    return card.querySelectorAll("input:not([type=checkbox])");
  }

  // Reflect a Stage's checkbox into its card: greyed + inputs disabled when off.
  // Disabling preserves the inputs' typed values, so re-enabling restores them.
  function syncStage(key) {
    var box = document.getElementById("stage-" + key + "-enabled");
    var card = document.getElementById("stage-" + key);
    if (!box || !card) return;
    var enabled = box.checked;
    card.classList.toggle("stage--disabled", !enabled);
    valueInputs(card).forEach(function (input) {
      input.disabled = !enabled;
    });
  }

  // ---- Save -----------------------------------------------------------------

  function text(id) {
    var el = document.getElementById(id);
    return el ? el.value.trim() : "";
  }

  // A numeric field's value as a Number, or null when blank/non-numeric. #200
  // does not validate (that is B3) — it just carries whatever was typed.
  function num(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    var raw = el.value.trim();
    if (raw === "") return null;
    var n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function optionalStage(domKey) {
    var box = document.getElementById("stage-" + domKey + "-enabled");
    return {
      enabled: box ? box.checked : true,
      temp: num("stage-" + domKey + "-temp"),
      time: num("stage-" + domKey + "-time"),
    };
  }

  function subStage(index) {
    var nameEl = document.getElementById("stage-amp-sub-" + index + "-name");
    return {
      name: nameEl ? nameEl.textContent.trim() : "",
      temp: num("stage-amp-sub-" + index + "-temp"),
      time: num("stage-amp-sub-" + index + "-time"),
    };
  }

  // Collect the Sub-stages as currently rendered (2 or 3, in DOM order), so the
  // payload reflects add/remove state and the two-/three-step names (#202).
  function collectSubstages() {
    var rows = document.querySelectorAll(".amp-substage");
    var list = [];
    for (var i = 0; i < rows.length; i++) {
      list.push(subStage(rows[i].getAttribute("data-sub")));
    }
    return list;
  }

  function estimatedMinutes() {
    var raw = text("profile-estimated-minutes");
    if (raw === "") return null;
    var parsed = Math.round(Number(raw));
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  // Build the POST body. All four stage keys are always present; an unchecked
  // Stage rides along as enabled:false with its preserved values.
  function buildPayload() {
    return {
      name: text("profile-name"),
      fam_label: text("profile-fam-label"),
      rox_label: text("profile-rox-label"),
      estimated_minutes: estimatedMinutes(),
      stages: {
        incubation: optionalStage("incubation"),
        denaturation: optionalStage("denaturation"),
        amplification: {
          cycles: num("stage-amp-cycles"),
          subStages: collectSubstages(),
        },
        finalHold: optionalStage("finalhold"),
      },
    };
  }

  async function saveProfile() {
    var status = document.getElementById("save-status");
    if (status) status.textContent = "Saving...";
    try {
      var response = await fetch("/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload()),
      });
      if (!response.ok) {
        var err = {};
        try {
          err = await response.json();
        } catch (e) {
          /* non-JSON error body */
        }
        if (status) status.textContent = err.detail || "Failed to save";
        return;
      }
      if (status) status.textContent = "Saved";
      window.location.href = "/profiles-page";
    } catch (e) {
      if (status) status.textContent = "Failed to save";
      console.error("Save failed", e);
    }
  }

  // ---- Amplification Sub-stages (issue #202) --------------------------------

  // Sub-stage 1's name depends on whether amplification is two- or three-step.
  var SECOND_NAME_TWO_STEP = "Annealing & Extension";
  var SECOND_NAME_THREE_STEP = "Annealing";
  var THIRD_NAME = "Extension";
  var MIN_SUBSTAGES = 2;
  var MAX_SUBSTAGES = 3;

  function substageRows() {
    return document.querySelectorAll(".amp-substage");
  }

  // The add tab shows only at two Sub-stages; at three the Extension row's own
  // X is the way back down, so the tab hides.
  function showAddTab(show) {
    var tab = document.getElementById("amp-add-substage");
    if (tab) tab.classList.toggle("is-hidden", !show);
  }

  // Build the third (Extension) row. It carries its own X remove control in a
  // header, since removal happens from the row itself, not a persistent button.
  function buildSubstageRow(index, name) {
    var row = document.createElement("div");
    row.className = "amp-substage amp-substage--removable";
    row.setAttribute("data-sub", String(index));
    // The name + fields live in a body column; the X is its sibling so it can
    // centre vertically against the whole row rather than hug the name line.
    row.innerHTML =
      '<div class="amp-substage__body">' +
      '<span class="amp-substage__name" id="stage-amp-sub-' + index + '-name"></span>' +
      '<div class="field-grid">' +
      '<div class="field">' +
      '<label for="stage-amp-sub-' + index + '-temp">Temp (°C)</label>' +
      '<input id="stage-amp-sub-' + index + '-temp" type="number" inputmode="numeric" value="" />' +
      '</div>' +
      '<div class="field">' +
      '<label for="stage-amp-sub-' + index + '-time">Time (s)</label>' +
      '<input id="stage-amp-sub-' + index + '-time" type="number" inputmode="numeric" value="" />' +
      '</div>' +
      '</div>' +
      '</div>' +
      '<button id="amp-remove-substage" class="amp-substage__remove" type="button" aria-label="Remove sub-stage">&times;</button>';
    // Set the name as text (never innerHTML) so it can't inject markup.
    row.querySelector(".amp-substage__name").textContent = name;
    row.querySelector("#amp-remove-substage").addEventListener("click", removeSubstage);
    return row;
  }

  // Two-step -> three-step: rename Sub-stage 1, append a blank Extension row, and
  // hide the add tab.
  function addSubstage() {
    if (substageRows().length >= MAX_SUBSTAGES) return;
    var second = document.getElementById("stage-amp-sub-1-name");
    if (second) second.textContent = SECOND_NAME_THREE_STEP;
    var container = document.querySelector(".amp-substages");
    if (container) container.appendChild(buildSubstageRow(2, THIRD_NAME));
    showAddTab(false);
  }

  // Three-step -> two-step: drop the Extension row, revert Sub-stage 1's name,
  // and bring the add tab back.
  function removeSubstage() {
    if (substageRows().length <= MIN_SUBSTAGES) return;
    var third = document.querySelector('.amp-substage[data-sub="2"]');
    if (third) third.remove();
    var second = document.getElementById("stage-amp-sub-1-name");
    if (second) second.textContent = SECOND_NAME_TWO_STEP;
    showAddTab(true);
  }

  // ---- Boot -----------------------------------------------------------------

  function init() {
    OPTIONAL_STAGES.forEach(function (key) {
      var box = document.getElementById("stage-" + key + "-enabled");
      if (!box) return;
      box.addEventListener("change", function () {
        syncStage(key);
      });
      syncStage(key); // sync initial state on load
    });

    var addBtn = document.getElementById("amp-add-substage");
    if (addBtn) addBtn.addEventListener("click", addSubstage);
    showAddTab(substageRows().length < MAX_SUBSTAGES);

    var saveButton = document.getElementById("save-profile-button");
    if (saveButton) saveButton.addEventListener("click", saveProfile);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
