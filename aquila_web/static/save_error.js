"use strict";
// Turn a profile-save failure response into something an operator can act on
// (issue #422).
//
// The server sends validation failures as {errors: [...]} and everything else
// as a plain string. Assigning the object straight to textContent rendered the
// literal "[object Object]", so an out-of-range field told the operator nothing
// at all. Anything unrecognised falls back rather than leaking a shape.

var DEFAULT_SAVE_ERROR = "Failed to save";

function formatSaveError(detail) {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (detail && Array.isArray(detail.errors) && detail.errors.length) {
    var messages = detail.errors.filter(function (e) {
      return typeof e === "string" && e.trim();
    });
    if (messages.length) {
      return messages.join("; ");
    }
  }
  return DEFAULT_SAVE_ERROR;
}

// Enable unit testing under Node (node:test) without affecting the browser,
// where `module` is undefined. Not a build step — a guarded CommonJS export.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { formatSaveError };
}
