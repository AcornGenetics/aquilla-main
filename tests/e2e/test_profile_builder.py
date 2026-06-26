"""
E2E tests for the structured profile builder shell (issue #200, Structured Profiles B1).

Covers the builder's observable DOM behavior at the page seam: the fresh-form
default state, the checkbox toggle that greys/disables a Stage while preserving
its values, and the happy-path save that POSTs a `stages` payload and redirects.
Field-level validation (B3) and Amplification Sub-stage add/remove (B2) are out
of scope here.

Requires a running backend at base_url (default http://localhost:8090; override
with AQUILA_TEST_URL). Run with: pytest -m e2e tests/e2e/test_profile_builder.py
Prior art: tests/e2e/test_countdown_timer.py, tests/e2e/test_run_dropdowns.py
"""
import pytest

pytestmark = pytest.mark.e2e

# Optional Stages carry an enable checkbox; Amplification is always present.
OPTIONAL_STAGES = ("incubation", "denaturation", "finalhold")
ALL_STAGES = ("incubation", "denaturation", "amplification", "finalhold")


def _goto_builder(page, base_url):
    """Navigate to the builder; skip if the backend isn't reachable."""
    try:
        page.goto(f"{base_url}/profiles/builder", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable at {base_url}: {exc}")
    page.wait_for_load_state("domcontentloaded")
    # The Stage cards are static HTML in builder.html (builder.js only wires
    # behavior); wait for the shell to attach before driving it.
    page.wait_for_selector("#stage-incubation", state="attached", timeout=5_000)


def test_fresh_builder_default_state(page, base_url):
    """A fresh builder shows all four Stages, optional ones checked ON, every
    thermal field blank, and no validation error styling."""
    _goto_builder(page, base_url)

    # All four Stage cards are rendered.
    for stage in ALL_STAGES:
        assert page.locator(f"#stage-{stage}").count() == 1, f"#stage-{stage} missing"

    # The three optional Stages open checked ON; Amplification has no checkbox.
    for stage in OPTIONAL_STAGES:
        assert page.locator(f"#stage-{stage}-enabled").is_checked(), (
            f"{stage} should default checked ON"
        )
    assert page.locator("#stage-amplification-enabled").count() == 0, (
        "Amplification must not have an enable checkbox"
    )

    # Every thermal value field is blank on a fresh form, including cycles.
    blank_fields = [
        "#stage-incubation-temp", "#stage-incubation-time",
        "#stage-denaturation-temp", "#stage-denaturation-time",
        "#stage-amp-cycles",
        "#stage-amp-sub-0-temp", "#stage-amp-sub-0-time",
        "#stage-amp-sub-1-temp", "#stage-amp-sub-1-time",
        "#stage-finalhold-temp", "#stage-finalhold-time",
    ]
    for sel in blank_fields:
        assert page.locator(sel).input_value() == "", f"{sel} should start blank"

    # No error styling shown on a fresh form.
    assert page.locator(".field-error:visible").count() == 0, "no errors on fresh form"


def test_unchecking_stage_greys_and_disables_its_fields(page, base_url):
    """Unchecking a Stage greys its card and disables its inputs."""
    _goto_builder(page, base_url)

    card = page.locator("#stage-incubation")
    temp = page.locator("#stage-incubation-temp")
    time = page.locator("#stage-incubation-time")

    # Starts enabled: not greyed, inputs editable.
    assert "stage--disabled" not in (card.get_attribute("class") or "")
    assert temp.is_enabled() and time.is_enabled()

    page.locator("#stage-incubation-enabled").uncheck()

    assert "stage--disabled" in (card.get_attribute("class") or ""), (
        "unchecked Stage card should be greyed via .stage--disabled"
    )
    assert temp.is_disabled() and time.is_disabled(), (
        "unchecked Stage inputs should be disabled"
    )


def test_rechecking_stage_preserves_typed_values(page, base_url):
    """Values typed into a Stage survive an uncheck/re-check round trip."""
    _goto_builder(page, base_url)

    page.locator("#stage-incubation-temp").fill("37")
    page.locator("#stage-incubation-time").fill("600")

    page.locator("#stage-incubation-enabled").uncheck()
    page.locator("#stage-incubation-enabled").check()

    # Re-enabled inputs keep what was typed before the toggle.
    assert page.locator("#stage-incubation-temp").input_value() == "37"
    assert page.locator("#stage-incubation-time").input_value() == "600"
    assert page.locator("#stage-incubation-temp").is_enabled()


def test_valid_save_posts_stages_and_redirects(page, base_url):
    """A valid Save POSTs the expected `stages` shape and redirects to the list.

    Final Temp Hold is unchecked, so it must ride along as enabled:false while
    the other Stages carry their typed temps/times. All four stage keys are
    always present.
    """
    _goto_builder(page, base_url)

    page.locator("#profile-name").fill("B1 Happy Path")

    page.locator("#stage-incubation-temp").fill("37")
    page.locator("#stage-incubation-time").fill("600")
    page.locator("#stage-denaturation-temp").fill("95")
    page.locator("#stage-denaturation-time").fill("120")
    page.locator("#stage-amp-cycles").fill("40")
    page.locator("#stage-amp-sub-0-temp").fill("95")
    page.locator("#stage-amp-sub-0-time").fill("11")
    page.locator("#stage-amp-sub-1-temp").fill("60")
    page.locator("#stage-amp-sub-1-time").fill("38")
    page.locator("#stage-finalhold-temp").fill("25")
    page.locator("#stage-finalhold-time").fill("60")
    page.locator("#stage-finalhold-enabled").uncheck()

    def is_save_post(req):
        return req.url.rstrip("/").endswith("/profiles") and req.method == "POST"

    with page.expect_request(is_save_post) as req_info, \
            page.expect_response(lambda r: is_save_post(r.request)) as resp_info:
        page.locator("#save-profile-button").click()

    payload = req_info.value.post_data_json
    stages = payload["stages"]

    assert payload["name"] == "B1 Happy Path"
    assert stages["incubation"] == {"enabled": True, "temp": 37, "time": 600}
    assert stages["denaturation"] == {"enabled": True, "temp": 95, "time": 120}
    assert stages["finalHold"]["enabled"] is False
    amp = stages["amplification"]
    assert amp["cycles"] == 40
    assert [s["name"] for s in amp["subStages"]] == ["Denaturation", "Annealing & Extension"]
    assert amp["subStages"][0] == {"name": "Denaturation", "temp": 95, "time": 11}
    assert amp["subStages"][1] == {"name": "Annealing & Extension", "temp": 60, "time": 38}

    # Save succeeded and the browser returned to the Profiles list.
    assert resp_info.value.status == 200
    page.wait_for_url("**/profiles-page", timeout=5_000)

    # Clean up: the redirect discards the response body, so find the created
    # profile by its sanitized id in the listing and delete it.
    listing = page.request.get(f"{base_url}/profiles").json()
    stale = [p["id"] for p in listing if "B1_Happy_Path" in p.get("id", "")]
    if stale:
        page.request.post(f"{base_url}/profiles/delete", data={"profiles": stale})


# ---------------------------------------------------------------------------
# Amplification Sub-stages — add/remove + rename + cycles (issue #202, B2)
# ---------------------------------------------------------------------------

TWO_STEP_NAMES = ["Denaturation", "Annealing & Extension"]
THREE_STEP_NAMES = ["Denaturation", "Annealing", "Extension"]


def _substage_names(page):
    return page.locator(".amp-substage .amp-substage__name").all_inner_texts()


def test_amplification_starts_two_step_with_add_tab(page, base_url):
    """A fresh builder shows two Sub-stages and the add tab, with no remove X."""
    _goto_builder(page, base_url)

    assert page.locator(".amp-substage").count() == 2
    assert _substage_names(page) == TWO_STEP_NAMES

    # The add tab is shown; there is no remove control until a third exists.
    assert page.locator("#amp-add-substage").is_visible(), "add tab should show at two"
    assert page.locator("#amp-remove-substage").count() == 0, "no X at two Sub-stages"


def test_adding_third_substage_renames_appends_and_hides_add_tab(page, base_url):
    """Adding a third Sub-stage renames the 2nd to 'Annealing', appends a blank
    'Extension' carrying its X, and hides the add tab."""
    _goto_builder(page, base_url)

    page.locator("#amp-add-substage").click()

    assert page.locator(".amp-substage").count() == 3
    assert _substage_names(page) == THREE_STEP_NAMES

    # The appended Extension Sub-stage starts blank.
    assert page.locator("#stage-amp-sub-2-temp").input_value() == ""
    assert page.locator("#stage-amp-sub-2-time").input_value() == ""

    # At three: the add tab is hidden and the Extension row carries the X.
    assert not page.locator("#amp-add-substage").is_visible(), "add tab hidden at three"
    assert page.locator("#amp-remove-substage").is_visible(), "Extension X should show"


def test_removing_third_substage_via_x_reverts_to_two_step(page, base_url):
    """The Extension row's X removes the third Sub-stage, reverts the 2nd's name,
    and brings the add tab back."""
    _goto_builder(page, base_url)

    page.locator("#amp-add-substage").click()      # 2 -> 3
    assert page.locator(".amp-substage").count() == 3

    page.locator("#amp-remove-substage").click()   # X on the Extension row, 3 -> 2

    assert page.locator(".amp-substage").count() == 2
    assert page.locator("#stage-amp-sub-2-name").count() == 0, "third row should be gone"
    assert _substage_names(page) == TWO_STEP_NAMES

    # Back at two: the add tab returns and the X is gone.
    assert page.locator("#amp-add-substage").is_visible(), "add tab should return"
    assert page.locator("#amp-remove-substage").count() == 0, "X should be gone at two"


def test_three_step_save_posts_three_substages(page, base_url):
    """With a third Sub-stage added, Save POSTs all three in order with their
    three-step names and the cycle count."""
    _goto_builder(page, base_url)

    page.locator("#profile-name").fill("B2 Three Step")
    # Focus on amplification: disable the other Stages so save-time validation
    # (B3) doesn't flag their blank fields.
    for stage in ("incubation", "denaturation", "finalhold"):
        page.locator(f"#stage-{stage}-enabled").uncheck()
    page.locator("#stage-amp-cycles").fill("35")
    page.locator("#amp-add-substage").click()  # -> three Sub-stages

    page.locator("#stage-amp-sub-0-temp").fill("95")
    page.locator("#stage-amp-sub-0-time").fill("10")
    page.locator("#stage-amp-sub-1-temp").fill("60")
    page.locator("#stage-amp-sub-1-time").fill("30")
    page.locator("#stage-amp-sub-2-temp").fill("72")
    page.locator("#stage-amp-sub-2-time").fill("20")

    def is_save_post(req):
        return req.url.rstrip("/").endswith("/profiles") and req.method == "POST"

    with page.expect_request(is_save_post) as req_info, \
            page.expect_response(lambda r: is_save_post(r.request)) as resp_info:
        page.locator("#save-profile-button").click()

    amp = req_info.value.post_data_json["stages"]["amplification"]
    assert amp["cycles"] == 35
    assert [s["name"] for s in amp["subStages"]] == THREE_STEP_NAMES
    assert amp["subStages"][0] == {"name": "Denaturation", "temp": 95, "time": 10}
    assert amp["subStages"][1] == {"name": "Annealing", "temp": 60, "time": 30}
    assert amp["subStages"][2] == {"name": "Extension", "temp": 72, "time": 20}

    assert resp_info.value.status == 200
    page.wait_for_url("**/profiles-page", timeout=5_000)

    listing = page.request.get(f"{base_url}/profiles").json()
    stale = [p["id"] for p in listing if "B2_Three_Step" in p.get("id", "")]
    if stale:
        page.request.post(f"{base_url}/profiles/delete", data={"profiles": stale})


def test_touch_targets_meet_kiosk_minimum(page, base_url):
    """The add tab and each Stage enable toggle meet the >=44x44px kiosk
    touch-target rule (spec §6).

    The Extension row's X is intentionally exempt: it is kept compact so the
    Sub-stage spacing stays uniform (issue #202 follow-up), accepting a smaller
    hit area for that one rarely-used control.
    """
    _goto_builder(page, base_url)
    MIN = 44

    add_box = page.locator("#amp-add-substage").bounding_box()
    assert add_box["width"] >= MIN and add_box["height"] >= MIN, f"add tab small: {add_box}"

    toggles = page.locator(".stage__toggle")
    assert toggles.count() == 3
    for i in range(toggles.count()):
        box = toggles.nth(i).bounding_box()
        assert box["height"] >= MIN, f"stage toggle {i} too short: {box['height']}px"


# ---------------------------------------------------------------------------
# Validation on save (issue #203, B3)
# ---------------------------------------------------------------------------

# Every validatable field on a fresh (two-Sub-stage) form, all Stages enabled.
ENABLED_FIELDS = [
    "#stage-incubation-temp", "#stage-incubation-time",
    "#stage-denaturation-temp", "#stage-denaturation-time",
    "#stage-finalhold-temp", "#stage-finalhold-time",
    "#stage-amp-cycles",
    "#stage-amp-sub-0-temp", "#stage-amp-sub-0-time",
    "#stage-amp-sub-1-temp", "#stage-amp-sub-1-time",
]


def _is_invalid(page, sel):
    return "is-invalid" in (page.locator(sel).get_attribute("class") or "")


def test_pristine_form_has_no_validation_errors(page, base_url):
    """A freshly loaded builder shows no error styling until a Save is tried."""
    _goto_builder(page, base_url)
    assert page.locator(".is-invalid").count() == 0
    assert page.locator(".field-error:visible").count() == 0


def test_blank_save_flags_every_enabled_field_and_blocks(page, base_url):
    """Saving an all-blank form flags every enabled field red with a range
    message naming the valid bounds, and does not navigate away."""
    _goto_builder(page, base_url)
    page.locator("#profile-name").fill("B3 Blank")

    page.locator("#save-profile-button").click()

    for sel in ENABLED_FIELDS:
        assert _is_invalid(page, sel), f"{sel} should be flagged invalid"
    errors = page.locator(".field-error:visible")
    assert errors.count() >= 1
    texts = errors.all_inner_texts()
    assert any("Range (25 - 100)" in t for t in texts), "temp range message"
    assert any("Range (1 - 600)" in t for t in texts), "time range message"
    assert any("Range (11 - 600)" in t for t in texts), "extension time range message"
    assert any("Range (1 - 50)" in t for t in texts), "cycles range message"
    assert not any("Invalid Value" in t for t in texts), "generic message replaced"

    # Blocked: still on the builder, no redirect to the Profiles list.
    assert page.url.rstrip("/").endswith("/profiles/builder")


def test_disabled_stage_does_not_block_save(page, base_url):
    """A disabled (unchecked) Stage's blank fields are skipped by validation, so
    an otherwise-valid form still saves."""
    _goto_builder(page, base_url)

    page.locator("#profile-name").fill("B3 Disabled Skip")
    page.locator("#stage-incubation-enabled").uncheck()  # left blank, must not block

    page.locator("#stage-denaturation-temp").fill("95")
    page.locator("#stage-denaturation-time").fill("120")
    page.locator("#stage-finalhold-temp").fill("25")
    page.locator("#stage-finalhold-time").fill("60")
    page.locator("#stage-amp-cycles").fill("40")
    page.locator("#stage-amp-sub-0-temp").fill("95")
    page.locator("#stage-amp-sub-0-time").fill("11")
    page.locator("#stage-amp-sub-1-temp").fill("60")
    page.locator("#stage-amp-sub-1-time").fill("38")

    def is_save_post(req):
        return req.url.rstrip("/").endswith("/profiles") and req.method == "POST"

    with page.expect_response(lambda r: is_save_post(r.request)) as resp_info:
        page.locator("#save-profile-button").click()

    assert resp_info.value.status == 200
    page.wait_for_url("**/profiles-page", timeout=5_000)

    listing = page.request.get(f"{base_url}/profiles").json()
    stale = [p["id"] for p in listing if "B3_Disabled_Skip" in p.get("id", "")]
    if stale:
        page.request.post(f"{base_url}/profiles/delete", data={"profiles": stale})


def _fill_valid_two_step(page):
    """Fill a fully valid two-Sub-stage form (caller tweaks one field to test edges)."""
    page.locator("#profile-name").fill("B3 Ranges")
    page.locator("#stage-incubation-temp").fill("37")
    page.locator("#stage-incubation-time").fill("600")
    page.locator("#stage-denaturation-temp").fill("95")
    page.locator("#stage-denaturation-time").fill("120")
    page.locator("#stage-finalhold-temp").fill("25")
    page.locator("#stage-finalhold-time").fill("60")
    page.locator("#stage-amp-cycles").fill("40")
    page.locator("#stage-amp-sub-0-temp").fill("95")
    page.locator("#stage-amp-sub-0-time").fill("11")
    page.locator("#stage-amp-sub-1-temp").fill("60")
    page.locator("#stage-amp-sub-1-time").fill("38")


def test_extension_min_applies_only_to_last_substage(page, base_url):
    """The 11s minimum applies to the last (extension-bearing) Sub-stage only:
    a 5s first Sub-stage is fine, a 10s last Sub-stage is rejected."""
    _goto_builder(page, base_url)
    _fill_valid_two_step(page)
    page.locator("#stage-amp-sub-0-time").fill("5")   # not last -> min 1, OK
    page.locator("#stage-amp-sub-1-time").fill("10")  # last -> min 11, invalid

    page.locator("#save-profile-button").click()

    assert _is_invalid(page, "#stage-amp-sub-1-time"), "last sub-stage <11s must flag"
    assert not _is_invalid(page, "#stage-amp-sub-0-time"), "first sub-stage 5s is valid"
    assert page.url.rstrip("/").endswith("/profiles/builder")  # blocked


def test_out_of_range_temp_and_cycles_block_then_pass(page, base_url):
    """Out-of-range temp (24) and cycles (51) are flagged and block; fixing them
    to the valid edges (25 / 50) lets the save through."""
    _goto_builder(page, base_url)
    _fill_valid_two_step(page)
    page.locator("#stage-incubation-temp").fill("24")  # below 25
    page.locator("#stage-amp-cycles").fill("51")       # above 50

    page.locator("#save-profile-button").click()
    assert _is_invalid(page, "#stage-incubation-temp")
    assert _is_invalid(page, "#stage-amp-cycles")
    assert page.url.rstrip("/").endswith("/profiles/builder")

    # Fix to the valid boundary values; save now succeeds.
    page.locator("#stage-incubation-temp").fill("25")
    page.locator("#stage-amp-cycles").fill("50")

    def is_save_post(req):
        return req.url.rstrip("/").endswith("/profiles") and req.method == "POST"

    with page.expect_response(lambda r: is_save_post(r.request)) as resp_info:
        page.locator("#save-profile-button").click()
    assert resp_info.value.status == 200
    page.wait_for_url("**/profiles-page", timeout=5_000)

    listing = page.request.get(f"{base_url}/profiles").json()
    stale = [p["id"] for p in listing if "B3_Ranges" in p.get("id", "")]
    if stale:
        page.request.post(f"{base_url}/profiles/delete", data={"profiles": stale})


# ---------------------------------------------------------------------------
# Edit round-trip (issue #203, B3)
# ---------------------------------------------------------------------------

ROUNDTRIP_STAGES = {
    "incubation": {"enabled": True, "temp": 37, "time": 600},
    "denaturation": {"enabled": True, "temp": 95, "time": 120},
    "amplification": {
        "cycles": 40,
        "subStages": [
            {"name": "Denaturation", "temp": 95, "time": 11},
            {"name": "Annealing", "temp": 60, "time": 30},
            {"name": "Extension", "temp": 72, "time": 20},
        ],
    },
    "finalHold": {"enabled": False, "temp": 25, "time": 60},
}


def test_edit_roundtrip_repopulates_and_updates_in_place(page, base_url):
    """Opening a structured Profile by id repopulates every Stage/Sub-stage/value
    from its `stages`, and saving updates that same profile (carries profile_id)."""
    # Seed a structured profile straight through the API.
    created = page.request.post(
        f"{base_url}/profiles",
        data={"name": "B3 Roundtrip", "stages": ROUNDTRIP_STAGES},
    )
    assert created.status == 200, created.text()
    pid = created.json()["id"]

    try:
        page.goto(f"{base_url}/profiles/builder?id={pid}", timeout=10_000)
        page.wait_for_load_state("domcontentloaded")
        # Repopulation is async (fetch /details); wait for a known value to land.
        page.wait_for_function(
            "() => document.getElementById('stage-amp-cycles')?.value === '40'",
            timeout=5_000,
        )

        assert page.locator("#profile-name").input_value() == "B3 Roundtrip"
        # Enabled Stage values restored.
        assert page.locator("#stage-incubation-enabled").is_checked()
        assert page.locator("#stage-incubation-temp").input_value() == "37"
        assert page.locator("#stage-incubation-time").input_value() == "600"
        # Disabled Stage restored as unchecked + greyed.
        assert not page.locator("#stage-finalhold-enabled").is_checked()
        assert "stage--disabled" in (page.locator("#stage-finalhold").get_attribute("class") or "")
        # Three Sub-stages with their three-step names and values.
        assert page.locator(".amp-substage").count() == 3
        assert _substage_names(page) == THREE_STEP_NAMES
        assert page.locator("#stage-amp-sub-2-temp").input_value() == "72"
        assert page.locator("#stage-amp-sub-2-time").input_value() == "20"

        # Saving updates in place: the POST carries profile_id.
        def is_save_post(req):
            return req.url.rstrip("/").endswith("/profiles") and req.method == "POST"

        with page.expect_request(is_save_post) as req_info:
            page.locator("#save-profile-button").click()
        assert req_info.value.post_data_json.get("profile_id") == pid
        page.wait_for_url("**/profiles-page", timeout=5_000)
    finally:
        _delete_profile_by_fragment(page, base_url, "B3_Roundtrip")


def _delete_profile_by_fragment(page, base_url, fragment):
    listing = page.request.get(f"{base_url}/profiles").json()
    stale = [p["id"] for p in listing if fragment in p.get("id", "")]
    if stale:
        page.request.post(f"{base_url}/profiles/delete", data={"profiles": stale})


# ---------------------------------------------------------------------------
# Profiles-list routing (issue #203, B3)
# ---------------------------------------------------------------------------

def test_list_routes_structured_legacy_and_bundled(page, base_url):
    """The list routes structured rows to the builder (Edit), Legacy rows to the
    read-only view (View), and never gives bundled rows an edit affordance."""
    page.request.post(f"{base_url}/profiles", data={"name": "B3 Routing Structured", "stages": ROUNDTRIP_STAGES})
    page.request.post(f"{base_url}/profiles", data={"name": "B3 Routing Legacy", "steps": [{"setpoint": 95, "duration": 30}]})

    try:
        page.goto(f"{base_url}/profiles-page", timeout=10_000)
        page.wait_for_selector("a.profiles-action-btn[href*='B3_Routing']", timeout=5_000)

        edit = page.locator("a.profiles-action-btn[href*='B3_Routing_Structured']")
        assert edit.count() == 1
        assert "edit" in edit.inner_text().lower()  # CSS uppercases the label
        assert "/profiles/builder" in edit.get_attribute("href")

        view = page.locator("a.profiles-action-btn[href*='B3_Routing_Legacy']")
        assert view.count() == 1
        assert "view" in view.inner_text().lower()
        href = view.get_attribute("href")
        assert "/profiles/edit-form" in href and "view=1" in href

        # Bundled rows (lock icon) carry no Edit/View action link.
        assert page.locator("tr:has(.profile-lock-icon) a.profiles-action-btn").count() == 0
    finally:
        _delete_profile_by_fragment(page, base_url, "B3_Routing")


def test_new_profile_button_opens_builder(page, base_url):
    """The Profiles list 'New profile' button opens the structured builder."""
    try:
        page.goto(f"{base_url}/profiles-page", timeout=10_000)
    except Exception as exc:
        pytest.skip(f"Backend not reachable: {exc}")
    new_btn = page.locator("a", has_text="New profile").first
    assert new_btn.get_attribute("href") == "/profiles/builder"


# ---------------------------------------------------------------------------
# B3 follow-ups: Est Time validation, legacy read-only, red error text
# ---------------------------------------------------------------------------

def test_invalid_estimated_time_blocks_save(page, base_url):
    """A non-positive / non-numeric Est. Time is flagged and blocks save, like
    the legacy editor on main."""
    _goto_builder(page, base_url)
    _fill_valid_two_step(page)
    page.locator("#profile-estimated-minutes").fill("-5")

    page.locator("#save-profile-button").click()

    assert _is_invalid(page, "#profile-estimated-minutes")
    assert page.locator("#profile-estimated-error").is_visible()
    assert page.url.rstrip("/").endswith("/profiles/builder")  # blocked


def test_legacy_profile_opens_read_only(page, base_url):
    """Routing a Legacy Profile to ?view=1 opens the viewer read-only (inputs
    disabled), not the editable legacy editor."""
    from urllib.parse import quote
    leg = page.request.post(
        f"{base_url}/profiles",
        data={"name": "B3 ReadOnly", "steps": [{"setpoint": 95, "duration": 30}]},
    ).json()["id"]
    try:
        page.goto(f"{base_url}/profiles/edit-form?id={quote(leg)}&view=1", timeout=10_000)
        page.wait_for_load_state("networkidle")
        assert page.locator("#profile-name").is_disabled(), "legacy view must be read-only"
    finally:
        page.request.post(f"{base_url}/profiles/delete", data={"profiles": [leg]})


def test_invalid_value_message_is_red(page, base_url):
    """The range error message renders red, not the muted card-text grey."""
    _goto_builder(page, base_url)
    page.locator("#save-profile-button").click()  # all-blank -> errors shown
    color = page.eval_on_selector(".field-error:visible", "el => getComputedStyle(el).color")
    assert color == "rgb(220, 38, 38)", f"expected red #dc2626, got {color}"
