"use strict";
// Unit tests for the Well Verdict precedence + dual-channel pill label
// (issue #181). Exercises the pure `summarizeResults` function.
// Run: node --test tests/unit/js/

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { summarizeResults } = require("../../../aquila_web/static/history_detail.js");

// Helper: build a results payload from per-tube {fam, rox} calls.
const results = (...tubes) => {
  const fam = {};
  const rox = {};
  tubes.forEach((t, i) => {
    fam[String(i + 1)] = t.fam;
    rox[String(i + 1)] = t.rox;
  });
  return { "1": fam, "2": rox };
};

test("Detected on either channel wins over Inconclusive (precedence)", () => {
  const s = summarizeResults(results({ fam: "Detected", rox: "Inconclusive" }));
  assert.equal(s.perTube[0], "detected");
});

test("mixed well label names both channels, Detected group first", () => {
  const s = summarizeResults(results({ fam: "Detected", rox: "Inconclusive" }));
  assert.equal(s.perTubeLabel[0], "Detected (FAM) Inconclusive (ROX)");
});

test("channels sharing a Call are grouped with ' + '", () => {
  const both = summarizeResults(results({ fam: "Detected", rox: "Detected" }));
  assert.equal(both.perTubeLabel[0], "Detected (FAM + ROX)");
  const none = summarizeResults(results({ fam: "Not Detected", rox: "Not Detected" }));
  assert.equal(none.perTubeLabel[0], "Not Detected (FAM + ROX)");
});

test("label orders groups by precedence: Inconclusive before Not Detected", () => {
  const s = summarizeResults(results({ fam: "Not Detected", rox: "Inconclusive" }));
  assert.equal(s.perTube[0], "inconclusive");
  assert.equal(s.perTubeLabel[0], "Inconclusive (ROX) Not Detected (FAM)");
});

test("label uses profile dye labels when provided", () => {
  const s = summarizeResults(
    results({ fam: "Detected", rox: "Inconclusive" }),
    { fam: "Target", rox: "Control" }
  );
  assert.equal(s.perTubeLabel[0], "Detected (Target) Inconclusive (Control)");
});

test("a Detected+Inconclusive well counts toward Detected only, never both", () => {
  const s = summarizeResults(results({ fam: "Detected", rox: "Inconclusive" }));
  assert.equal(s.detectedCount, 1);
  assert.equal(s.inconclusiveCount, 0);
});

test("QC flag is channel-sensitive: true when any channel is inconclusive even if the verdict is Detected", () => {
  const flagged = summarizeResults(results({ fam: "Detected", rox: "Inconclusive" }));
  assert.equal(flagged.perTube[0], "detected");
  assert.equal(flagged.anyChannelInconclusive, true);

  const clean = summarizeResults(results({ fam: "Detected", rox: "Not Detected" }));
  assert.equal(clean.anyChannelInconclusive, false);
});

test("missing results yield a clean, QC-Pass summary", () => {
  const s = summarizeResults(null);
  assert.equal(s.detectedCount, 0);
  assert.equal(s.inconclusiveCount, 0);
  assert.equal(s.anyChannelInconclusive, false);
});

test("ROX Unavailable is excluded from verdict and label; FAM shown alone", () => {
  const det = summarizeResults(results({ fam: "Detected", rox: "ROX Unavailable" }), { fam: "Target", rox: "Control" });
  assert.equal(det.perTube[0], "detected");
  assert.equal(det.perTubeLabel[0], "Detected (Target)");

  const nd = summarizeResults(results({ fam: "Not Detected", rox: "ROX Unavailable" }));
  assert.equal(nd.perTube[0], "not-detected");
  assert.equal(nd.perTubeLabel[0], "Not Detected (FAM)");
});
