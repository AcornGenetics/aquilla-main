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
          subStages: [subStage(0), subStage(1)],
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

    var saveButton = document.getElementById("save-profile-button");
    if (saveButton) saveButton.addEventListener("click", saveProfile);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
