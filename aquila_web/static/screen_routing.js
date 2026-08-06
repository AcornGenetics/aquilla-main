"use strict";
// Where the browser belongs for a given server-reported screen (issue #421).
//
// Returns a path to navigate to, or null to stay put and let the current page
// update itself in place.
//
// A fault carries its own "error" screen rather than sharing "init" with boot
// and the Exit confirmation flow. That separation matters: the Run screen maps
// "init" onto "ready", so while faults rode on "init" an instrument failure was
// silently rendered as a healthy Ready screen. "error" always navigates, from
// the dashboard and the legacy screens alike.

function screenDestination(screen, isDashboardPage) {
  if (screen === "error") {
    return "/error";
  }
  if (isDashboardPage) {
    // The dashboard owns ready/running/complete in place, and treats the boot
    // "init" state as ready. None of those are navigations.
    return null;
  }
  if (screen === "init") {
    return "/";
  }
  if (screen === "ready") {
    return "/ready";
  }
  if (screen === "running") {
    return "/run";
  }
  if (screen === "complete") {
    return "/complete";
  }
  return null;
}

// Enable unit testing under Node (node:test) without affecting the browser,
// where `module` is undefined. Not a build step — a guarded CommonJS export.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { screenDestination };
}
