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


# --- image retention (#397) -------------------------------------------------
# Nothing has ever removed an image from these devices, and Greengrass does not do
# it either: sn01 was measured still holding its previous deployment's 1.17 GB ECR
# image after a later deployment. The recipe is what makes the prune run.

PRUNE_URI = "s3://bucket/com.acorn.sentri/0.1.5/prune-images.sh"


def _recipe_with_prune():
    return build_recipe(
        "com.acorn.sentri",
        "0.1.5",
        "s3://bucket/com.acorn.sentri/0.1.5/compose.yaml",
        image_refs=["ecr/api@sha256:a", "ecr/ui@sha256:b"],
        prune_artifact_uri=PRUNE_URI,
    )


def _run_step(recipe):
    return recipe["Manifests"][0]["Lifecycle"]["Run"]


def test_recipe_declares_the_prune_script_as_an_artifact():
    """Shipped with the component so it is versioned and ring-promoted, rather than
    frozen at provisioning like every other host script."""
    uris = [a["URI"] for a in _recipe_with_prune()["Manifests"][0]["Artifacts"]]

    assert PRUNE_URI in uris


def test_prune_runs_after_the_stack_is_up():
    """It must run once the new containers hold their images — that is both when an
    image has just been superseded and what protects the current one from removal."""
    run = _run_step(_recipe_with_prune())

    assert "prune-images.sh" in run
    assert run.index("docker compose") < run.index("prune-images.sh")


def test_prune_is_run_with_bash_not_sh():
    """On Debian /bin/sh is dash; the script uses [[ ]] and here-strings, so invoking
    it with sh would fail on every device. Naming the interpreter also avoids relying
    on Greengrass preserving the artifact's executable bit."""
    run = _run_step(_recipe_with_prune())

    assert 'bash "{artifacts:path}/prune-images.sh"' in run


def test_prune_failure_cannot_break_the_component():
    """A non-zero exit from Run marks the component BROKEN and triggers a rollback.
    Disk cleanup must never be able to take the instrument down."""
    run = _run_step(_recipe_with_prune())
    prune_call = run[run.index("prune-images.sh"):]

    assert prune_call.startswith('prune-images.sh" || true')


def test_prune_does_not_delay_the_health_gate():
    """The health monitor is what keeps the component RUNNING; pruning ahead of the
    startup buffer would eat into it, so it must come before the sleep, not inside
    the polling loop."""
    run = _run_step(_recipe_with_prune())

    assert run.index("prune-images.sh") < run.index("sleep 25")


def test_recipe_without_a_prune_uri_is_unchanged():
    """Publishing without the script must still yield a working recipe — the device
    simply does not prune."""
    recipe = build_recipe(
        "com.acorn.sentri",
        "0.1.5",
        "s3://bucket/com.acorn.sentri/0.1.5/compose.yaml",
        image_refs=["ecr/api@sha256:a"],
    )

    assert "prune-images.sh" not in _run_step(recipe)
    assert "docker compose" in _run_step(recipe)


def test_compose_path_is_still_formatted_correctly_with_the_prune_step():
    """Regression: the Run string is built by concatenation, and `%` binds tighter
    than `+` — a stray format operator would leave a literal %s in the command."""
    run = _run_step(_recipe_with_prune())

    assert "%s" not in run
    assert "{artifacts:path}/compose.yaml" in run
