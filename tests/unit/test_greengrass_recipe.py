"""
Unit tests for the Greengrass component recipe builder.

The recipe is the manifest AWS IoT Greengrass stores for each published
component version: it names the component, pins its version, and points at the
docker-compose artifact (in S3) the device runs. These are pure functions — no
AWS, no network — so they exercise the real artifact-shaping logic directly.

Behaviors tested:
  1. build_recipe stamps the component name and version into a valid recipe
  2. build_recipe pins the compose artifact and runs it via a Lifecycle
  3. pin_compose rewrites the app images to the ECR digest refs
  4. pin_compose strips build sections (the device pulls, never builds)
"""
import pytest

pytestmark = pytest.mark.unit

from scripts.greengrass.recipe import build_recipe, pin_compose


def _device_compose():
    """The on-device compose as authored: floating GHCR tags + build sections."""
    return {
        "services": {
            "backend": {
                "build": {"context": ".", "dockerfile": "docker/Dockerfile.api"},
                "image": "ghcr.io/acorngenetics/aquilla-main-api:latest",
            },
            "ui": {
                "build": {"context": ".", "dockerfile": "docker/Dockerfile.ui"},
                "image": "ghcr.io/acorngenetics/aquilla-main-ui:latest",
            },
        }
    }


API_DIGEST = "867958227555.dkr.ecr.us-east-2.amazonaws.com/aquilla-main-api@sha256:aaa"
UI_DIGEST = "867958227555.dkr.ecr.us-east-2.amazonaws.com/aquilla-main-ui@sha256:bbb"


def test_build_recipe_sets_name_and_version():
    recipe = build_recipe(
        component_name="com.acorn.sentri",
        version="1.2.3",
        compose_artifact_uri="s3://acorn-artifacts/com.acorn.sentri/1.2.3/compose.yaml",
    )

    assert recipe["RecipeFormatVersion"] == "2020-01-25"
    assert recipe["ComponentName"] == "com.acorn.sentri"
    assert recipe["ComponentVersion"] == "1.2.3"


def test_recipe_manifest_pins_compose_artifact_and_runs_it():
    uri = "s3://acorn-artifacts/com.acorn.sentri/1.2.3/compose.yaml"
    recipe = build_recipe("com.acorn.sentri", "1.2.3", uri)

    manifest = recipe["Manifests"][0]
    artifact_uris = [artifact["URI"] for artifact in manifest["Artifacts"]]
    assert uri in artifact_uris

    # The device brings the stack up from the downloaded compose artifact.
    run = manifest["Lifecycle"]["Run"]
    assert "docker compose" in run
    assert "up" in run


def test_pin_compose_sets_images_to_digest_refs():
    pinned = pin_compose(_device_compose(), API_DIGEST, UI_DIGEST)

    assert pinned["services"]["backend"]["image"] == API_DIGEST
    assert pinned["services"]["ui"]["image"] == UI_DIGEST


def test_pin_compose_strips_build_sections():
    pinned = pin_compose(_device_compose(), API_DIGEST, UI_DIGEST)

    assert "build" not in pinned["services"]["backend"]
    assert "build" not in pinned["services"]["ui"]


def test_pin_compose_does_not_mutate_the_input():
    original = _device_compose()
    pin_compose(original, API_DIGEST, UI_DIGEST)

    # The authored compose is reused across builds — pinning must not clobber it.
    assert original["services"]["backend"]["image"].startswith("ghcr.io/")
    assert "build" in original["services"]["backend"]
