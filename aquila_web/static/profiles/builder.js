// Structured profile builder (issue #200, Structured Profiles B1).
// The markup lives in builder.html; this script wires behavior: Stage enable
// toggles (grey/disable while preserving values) and save. Field validation is
// B3; Amplification Sub-stage add/remove is B2.
(function () {
  "use strict";

  // Stages with an enable checkbox. Amplification is always present (no toggle).
  var OPTIONAL_STAGES = ["incubation", "denaturation", "finalhold"];

  // When the URL carries ?id= (or ?profile=) the builder is editing an existing
  // structured Profile: it repopulates from `stages` and saves in place (#203).
  var editId =
    new URLSearchParams(window.location.search).get("id") ||
    new URLSearchParams(window.location.search).get("profile");

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
  // Stage rides along as enabled:false with its preserved values. In edit mode
  // profile_id is included so the backend updates that profile in place.
  function buildPayload() {
    var payload = {
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
    if (editId) payload.profile_id = editId;
    return payload;
  }

  // ---- Validation (issue #203) ----------------------------------------------
  // Ranges mirror aquila_web/profile_assembly.py::validate_stages so a
  // client-valid form never trips the server's 400 (which stays the safety net).
  var TEMP_MIN = 25, TEMP_MAX = 100;
  var TIME_MIN = 1, TIME_MAX = 600, EXTENSION_TIME_MIN = 11;
  var CYCLES_MIN = 1, CYCLES_MAX = 50;

  function validTemp(v) {
    return typeof v === "number" && v >= TEMP_MIN && v <= TEMP_MAX;
  }
  function validTime(v, min) {
    return typeof v === "number" && v >= min && v <= TIME_MAX;
  }
  function validCycles(v) {
    return Number.isInteger(v) && v >= CYCLES_MIN && v <= CYCLES_MAX;
  }

  // Ensure a hidden "Invalid Value" message exists right after the input.
  function errorEl(input) {
    var next = input.nextElementSibling;
    if (next && next.classList.contains("field-error")) return next;
    var p = document.createElement("p");
    p.className = "field-error is-hidden";
    p.textContent = "Invalid Value";
    input.insertAdjacentElement("afterend", p);
    return p;
  }

  function setFieldValid(id, ok) {
    var input = document.getElementById(id);
    if (!input) return ok;
    input.classList.toggle("is-invalid", !ok);
    errorEl(input).classList.toggle("is-hidden", ok);
    return ok;
  }

  // Est. Time (Min) — optional; blank is fine, otherwise a positive integer.
  // Mirrors the legacy editor's check (edit.js) so the field behaves the same.
  function validEstimated() {
    var el = document.getElementById("profile-estimated-minutes");
    if (!el) return true;
    var raw = el.value.trim();
    if (raw === "") return true;
    var parsed = Math.round(Number(raw));
    return Number.isFinite(parsed) && parsed > 0;
  }

  function setEstimatedValid(ok) {
    var input = document.getElementById("profile-estimated-minutes");
    var err = document.getElementById("profile-estimated-error");
    if (input) input.classList.toggle("is-invalid", !ok);
    if (err) err.classList.toggle("is-hidden", ok);
    return ok;
  }

  // Validate every enabled-Stage field; flag all offenders at once. Disabled
  // Stages are skipped (and any stale error on them cleared). Returns validity.
  function validateForm() {
    var valid = setEstimatedValid(validEstimated());

    OPTIONAL_STAGES.forEach(function (key) {
      var box = document.getElementById("stage-" + key + "-enabled");
      var enabled = !box || box.checked;
      if (!enabled) {
        setFieldValid("stage-" + key + "-temp", true);
        setFieldValid("stage-" + key + "-time", true);
        return;
      }
      valid = setFieldValid("stage-" + key + "-temp", validTemp(num("stage-" + key + "-temp"))) && valid;
      valid = setFieldValid("stage-" + key + "-time", validTime(num("stage-" + key + "-time"), TIME_MIN)) && valid;
    });

    valid = setFieldValid("stage-amp-cycles", validCycles(num("stage-amp-cycles"))) && valid;

    var rows = document.querySelectorAll(".amp-substage");
    for (var i = 0; i < rows.length; i++) {
      var idx = rows[i].getAttribute("data-sub");
      var isLast = i === rows.length - 1; // extension-bearing Sub-stage
      var minTime = isLast ? EXTENSION_TIME_MIN : TIME_MIN;
      valid = setFieldValid("stage-amp-sub-" + idx + "-temp", validTemp(num("stage-amp-sub-" + idx + "-temp"))) && valid;
      valid = setFieldValid("stage-amp-sub-" + idx + "-time", validTime(num("stage-amp-sub-" + idx + "-time"), minTime)) && valid;
    }

    return valid;
  }

  async function saveProfile() {
    var status = document.getElementById("save-status");
    // Validate on save only (never on load); block + flag every offender.
    if (!validateForm()) {
      var firstBad = document.querySelector(".is-invalid");
      if (firstBad) firstBad.scrollIntoView({ block: "center", behavior: "smooth" });
      if (status) status.textContent = "";
      return;
    }
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

  // ---- Edit round-trip (issue #203) -----------------------------------------

  function setVal(id, value) {
    var el = document.getElementById(id);
    if (el && value !== undefined && value !== null) el.value = value;
  }

  function populateOptionalStage(key, stage) {
    if (!stage) return;
    var box = document.getElementById("stage-" + key + "-enabled");
    if (box) box.checked = !!stage.enabled;
    setVal("stage-" + key + "-temp", stage.temp);
    setVal("stage-" + key + "-time", stage.time);
    syncStage(key); // grey/disable when restored as unchecked
  }

  // Repopulate the builder from an existing structured Profile's `stages`.
  async function loadForEdit(id) {
    try {
      var resp = await fetch("/profiles/details?id=" + encodeURIComponent(id));
      if (!resp.ok) return;
      var data = await resp.json();
      var stages = data.stages;
      if (!stages) return; // not a Structured Profile — leave blank defaults

      var titleText = document.getElementById("builder-title-text");
      if (titleText) titleText.textContent = "Edit Profile";

      setVal("profile-name", data.title);
      var labels = data.labels || {};
      setVal("profile-fam-label", labels.fam);
      setVal("profile-rox-label", labels.rox);
      var secs = data.estimated_completion_seconds;
      if (typeof secs === "number" && secs > 0) {
        setVal("profile-estimated-minutes", Math.round(secs / 60));
      }

      populateOptionalStage("incubation", stages.incubation);
      populateOptionalStage("denaturation", stages.denaturation);
      populateOptionalStage("finalhold", stages.finalHold);

      var amp = stages.amplification || {};
      setVal("stage-amp-cycles", amp.cycles);
      var subs = amp.subStages || [];
      if (subs.length === 3) addSubstage(); // build + name the third row
      for (var i = 0; i < subs.length; i++) {
        setVal("stage-amp-sub-" + i + "-temp", subs[i].temp);
        setVal("stage-amp-sub-" + i + "-time", subs[i].time);
      }
    } catch (e) {
      console.error("Failed to load profile for edit", e);
    }
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

    if (editId) loadForEdit(editId);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
