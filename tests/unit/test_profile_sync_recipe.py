"""
Unit tests for the com.acorn.profile-sync Greengrass recipe builder (ADR-022).

profile-sync is its OWN component with its OWN container (aquila-profile-sync), so
it has the same version-switch hazard the sentri stack had (#515): the compose
project name defaulted to the artifact dir (the version), so each version ran as a
separate project, and a cut-off teardown could leave an Exited aquila-profile-sync
that squats the name and makes the next `up` fail with a Conflict.

These are pure functions — no AWS, no network — so they exercise the real
lifecycle-string logic directly.
"""
import pytest

pytestmark = pytest.mark.unit

from scripts.greengrass.recipe import COMPOSE_PROJECT as SENTRI_PROJECT
from scripts.greengrass.publish_profile_sync import PROFILE_SYNC_PROJECT, build_recipe

URI = "s3://bucket/com.acorn.profile-sync/0.1.5/profile-sync-compose.yaml"
API_DIGEST = "867958227555.dkr.ecr.us-east-2.amazonaws.com/aquilla-main-api@sha256:aaa"


def _recipe():
    return build_recipe("0.1.5", URI, API_DIGEST)


def _run(recipe):
    return recipe["Manifests"][0]["Lifecycle"]["Run"]


def _shutdown(recipe):
    return recipe["Manifests"][0]["Lifecycle"]["Shutdown"]


def test_run_uses_a_stable_project_name_distinct_from_the_sentri_stack():
    """profile-sync must pin its own stable compose project — and it MUST differ from
    the sentri stack's project, or the sentri `up --remove-orphans` would treat the
    profile-sync container as an orphan and reap it."""
    run = _run(_recipe())

    assert ("docker compose -p %s" % PROFILE_SYNC_PROJECT) in run
    assert PROFILE_SYNC_PROJECT != SENTRI_PROJECT


def test_run_sweeps_its_own_container_before_up():
    """A cut-off teardown can leave an Exited aquila-profile-sync squatting the name.
    Force-remove it before `up` so the switch can't collide with a corpse."""
    run = _run(_recipe())

    assert "docker rm -f aquila-profile-sync" in run
    assert run.index("docker rm -f") < run.index("docker compose")


def test_run_does_not_touch_the_sentri_stack_containers():
    """profile-sync must only ever manage its own container — never the sentri stack's
    backend/app/ui."""
    run = _run(_recipe())

    for name in ("aquila-backend", "aquila-app", "aquila-ui"):
        assert name not in run


def test_run_up_removes_orphans():
    run = _run(_recipe())

    assert "up --remove-orphans" in run


def test_shutdown_tears_down_under_the_same_stable_project_name():
    shutdown = _shutdown(_recipe())

    assert ("docker compose -p %s" % PROFILE_SYNC_PROJECT) in shutdown
    assert "down" in shutdown
    assert "--remove-orphans" in shutdown


def test_lifecycle_strings_are_formatted_correctly():
    """Regression: the lifecycle strings interpolate via `%` — a mismatched tuple would
    leave a literal %s in the command."""
    recipe = _recipe()

    assert "%s" not in _run(recipe)
    assert "%s" not in _shutdown(recipe)
    assert "{artifacts:path}/profile-sync-compose.yaml" in _run(recipe)
