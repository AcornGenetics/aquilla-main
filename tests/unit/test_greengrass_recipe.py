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
  5. build_recipe depends on DockerApplicationManager to pre-stage the images
  6. build_recipe declares the app images as docker artifacts (pre-staged)
  7. build_recipe reports the app /health as the component health
  8. pin_compose also pins the app service (shares the api image)
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


def test_pin_compose_also_pins_the_app_service():
    compose = _device_compose()
    compose["services"]["app"] = {"image": "ghcr.io/acorngenetics/aquilla-main-api:latest"}

    pinned = pin_compose(compose, API_DIGEST, UI_DIGEST)

    # app shares the api image, so it pins to the same digest as backend.
    assert pinned["services"]["app"]["image"] == API_DIGEST


def test_pin_compose_does_not_mutate_the_input():
    original = _device_compose()
    pin_compose(original, API_DIGEST, UI_DIGEST)

    # The authored compose is reused across builds — pinning must not clobber it.
    assert original["services"]["backend"]["image"].startswith("ghcr.io/")
    assert "build" in original["services"]["backend"]


def _recipe_with_images():
    return build_recipe(
        "com.acorn.sentri",
        "1.2.3",
        "s3://acorn-artifacts/com.acorn.sentri/1.2.3/compose.yaml",
        image_refs=[API_DIGEST, UI_DIGEST],
    )


def test_recipe_depends_on_docker_application_manager():
    deps = _recipe_with_images()["ComponentDependencies"]
    # Greengrass pre-stages the ECR images via DockerApplicationManager.
    assert "aws.greengrass.DockerApplicationManager" in deps


def test_recipe_depends_on_token_exchange_service():
    deps = _recipe_with_images()["ComponentDependencies"]
    # Private ECR pulls require the Token Exchange Service; as a recipe dependency
    # every deployment includes it automatically (no manual add per ring).
    assert "aws.greengrass.TokenExchangeService" in deps


def test_recipe_depends_on_shadow_manager():
    deps = _recipe_with_images()["ComponentDependencies"]
    # The update agent publishes the Device Shadow over IPC (am#382/#395); the
    # ShadowManager component is what services those shadow IPC ops on-device.
    # As a recipe dependency it ships with every deployment.
    assert "aws.greengrass.ShadowManager" in deps


def _shadow_access_policies(recipe):
    ac = recipe["ComponentConfiguration"]["DefaultConfiguration"]["accessControl"]
    return ac["aws.greengrass.ShadowManager"]


def test_recipe_authorizes_the_shadow_ipc_operations():
    # Shadow IPC ops are denied without an accessControl policy — this is exactly
    # why publish_health() failed silently on sn01. Grant get + update.
    policies = _shadow_access_policies(_recipe_with_images())
    ops = [op for pol in policies.values() for op in pol["operations"]]
    assert "aws.greengrass#UpdateThingShadow" in ops
    assert "aws.greengrass#GetThingShadow" in ops


def test_shadow_access_is_scoped_to_the_devices_own_shadow():
    # Least privilege (PRD testing decision): the component may touch only THIS
    # core device's classic shadow, not every thing's shadow.
    policies = _shadow_access_policies(_recipe_with_images())
    resources = [r for pol in policies.values() for r in pol["resources"]]
    assert "*" not in resources
    assert any("{iot:thingName}" in r and r.endswith("/shadow") for r in resources)


def test_recipe_declares_images_as_docker_artifacts():
    artifacts = _recipe_with_images()["Manifests"][0]["Artifacts"]
    uris = [a["URI"] for a in artifacts]
    # docker: URIs tell DockerApplicationManager which images to pre-stage.
    assert f"docker:{API_DIGEST}" in uris
    assert f"docker:{UI_DIGEST}" in uris


def test_recipe_reports_health_from_slash_health():
    run = _recipe_with_images()["Manifests"][0]["Lifecycle"]["Run"]
    # Component liveness is gated on the app's /health endpoint.
    assert "/health" in run


def test_recipe_health_gate_waits_for_startup():
    run = _recipe_with_images()["Manifests"][0]["Lifecycle"]["Run"]
    # A 25s buffer + grace loop so a slow first boot doesn't instantly break the
    # component (the app takes ~15s to become healthy after compose up).
    assert "sleep 25" in run  # buffer before the first health check
    assert "seq" in run       # grace loop after the buffer


def test_recipe_exports_thing_name_for_ipc():
    # The container reaches Greengrass Core IPC (to publish its shadow + defer
    # updates, am#382) using SVCUID + the nucleus socket path — both already in the
    # component process env, so compose passes them through. The thing name is not,
    # so the recipe exports it (via the {iot:thingName} recipe variable) for the
    # agent to address its own Device Shadow.
    run = _recipe_with_images()["Manifests"][0]["Lifecycle"]["Run"]
    assert "AWS_IOT_THING_NAME" in run
    assert "{iot:thingName}" in run
