"use strict";
// Unit tests for the delete-confirmation copy builders (issue #261).
// Exercises the pure `historyDeleteCopy` / `profilesDeleteCopy` functions that
// produce the modal's title/message/detail text — the only real logic in the
// confirm-modal feature. The modal DOM behavior is covered at the e2e seam.
// Run: node --test tests/unit/js/confirm_copy.test.js

const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  historyDeleteCopy,
  profilesDeleteCopy,
} = require("../../../aquila_web/static/confirm-modal.js");

test("historyDeleteCopy names the single selected run", () => {
  const copy = historyDeleteCopy(["Run A"]);
  assert.match(copy.message, /Run A/);
  assert.doesNotMatch(copy.message, /runs/);
});

test("historyDeleteCopy collapses multiple runs to a count", () => {
  const copy = historyDeleteCopy(["Run A", "Run B"]);
  assert.match(copy.message, /2 runs/);
  assert.doesNotMatch(copy.message, /Run A/);
});

test("profilesDeleteCopy uses singular for one profile and lists its name", () => {
  const copy = profilesDeleteCopy(["Protocol X"]);
  assert.match(copy.message, /1 profile\b/);
  assert.doesNotMatch(copy.message, /profiles/);
  assert.match(copy.detail, /Protocol X/);
});

test("profilesDeleteCopy pluralizes the count", () => {
  const copy = profilesDeleteCopy(["a", "b", "c"]);
  assert.match(copy.message, /3 profiles/);
});

test("profilesDeleteCopy truncates the name list beyond three", () => {
  const copy = profilesDeleteCopy(["p1", "p2", "p3", "p4", "p5"]);
  assert.match(copy.detail, /p1, p2, p3 and 2 more/);
  assert.doesNotMatch(copy.detail, /p4|p5/);
  // count is still the true total, not the truncated display
  assert.match(copy.message, /5 profiles/);
});
