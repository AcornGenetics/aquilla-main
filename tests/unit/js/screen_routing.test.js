"use strict";
// Unit tests for the screen -> destination decision (issue #421).
// Run: node --test tests/unit/js/
//
// A fault previously shared the "init" screen with boot and the Exit flow, and
// the Run screen rewrote "init" to "ready" — so an instrument fault left the
// operator staring at a healthy-looking Ready screen. Faults now have their own
// screen value and must always pull the operator to the general error page.

const { test } = require("node:test");
const assert = require("node:assert/strict");
const { screenDestination } = require("../../../aquila_web/static/screen_routing.js");

const DASHBOARD = true;
const LEGACY = false;

test("a fault sends the operator to the error page from the dashboard", () => {
  assert.equal(screenDestination("error", DASHBOARD), "/error");
});

test("a fault sends the operator to the error page from a legacy screen", () => {
  assert.equal(screenDestination("error", LEGACY), "/error");
});

test("the dashboard handles its own screens in place", () => {
  assert.equal(screenDestination("ready", DASHBOARD), null);
  assert.equal(screenDestination("running", DASHBOARD), null);
  assert.equal(screenDestination("complete", DASHBOARD), null);
});

test("boot does not drag the dashboard anywhere", () => {
  // State 0 (initialising) and the Exit flow still report "init"; they are not
  // faults and must not navigate.
  assert.equal(screenDestination("init", DASHBOARD), null);
});

test("legacy screens still navigate to their own pages", () => {
  assert.equal(screenDestination("init", LEGACY), "/");
  assert.equal(screenDestination("ready", LEGACY), "/ready");
  assert.equal(screenDestination("running", LEGACY), "/run");
  assert.equal(screenDestination("complete", LEGACY), "/complete");
});

test("an unrecognised screen never navigates", () => {
  assert.equal(screenDestination("banana", DASHBOARD), null);
  assert.equal(screenDestination(undefined, LEGACY), null);
});
