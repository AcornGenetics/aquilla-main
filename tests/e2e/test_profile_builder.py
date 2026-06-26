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
