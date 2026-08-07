"use strict";
// Unit tests for the profile-save error formatting (issue #422).
// Run: node --test tests/unit/js/save_error.test.js
//
// The server returns validation failures as a structured object
// ({errors: [...]}), and the editor assigned it straight to textContent — so an
// out-of-range field showed the operator the literal string "[object Object]"
// instead of naming the field that was wrong.

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { formatSaveError } = require("../../../aquila_web/static/save_error.js");

test("a validation failure names the offending field", () => {
  const detail = { errors: ["incubation.temp: Invalid Value"] };
  assert.equal(formatSaveError(detail), "incubation.temp: Invalid Value");
});

test("every offending field is shown, not just the first", () => {
  const detail = {
    errors: ["incubation.temp: Invalid Value", "amplification.cycles: Invalid Value"],
  };
  const out = formatSaveError(detail);
  assert.match(out, /incubation\.temp/);
  assert.match(out, /amplification\.cycles/);
});

test("a plain string detail is passed through", () => {
  assert.equal(
    formatSaveError("Bundled profiles are read-only."),
    "Bundled profiles are read-only."
  );
});

test("a missing detail falls back to a usable message", () => {
  assert.equal(formatSaveError(undefined), "Failed to save");
  assert.equal(formatSaveError(null), "Failed to save");
});

test("an unexpected shape never renders as [object Object]", () => {
  for (const detail of [{}, { errors: [] }, { errors: "nope" }, { other: 1 }, []]) {
    const out = formatSaveError(detail);
    assert.doesNotMatch(out, /\[object Object\]/, `leaked for ${JSON.stringify(detail)}`);
    assert.ok(out.length > 0);
  }
});
