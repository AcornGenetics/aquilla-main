"""Build the AWS IoT Greengrass component recipe for the on-device app stack.

Pure functions only — the CI workflow feeds in the image digests and the S3 URI
of the compose artifact, and gets back the recipe dict to hand to
`greengrassv2 create-component-version`. No AWS calls live here.
"""
import copy

# The recipe schema version Greengrass v2 expects.
RECIPE_FORMAT_VERSION = "2020-01-25"


def pin_compose(compose, api_ref, ui_ref):
    """Rewrite the on-device compose to run the exact built images by digest.

    The authored compose uses floating GHCR tags and `build:` sections. On the
    device we never build — Greengrass deploys prebuilt images, pinned by ECR
    digest so a deployment is byte-for-byte the artifact CI published.
    """
    pinned = copy.deepcopy(compose)
    for service, ref in (("backend", api_ref), ("ui", ui_ref)):
        pinned["services"][service]["image"] = ref
        pinned["services"][service].pop("build", None)
    return pinned


def build_recipe(component_name, version, compose_artifact_uri):
    """Return the Greengrass recipe for a published component version."""
    compose_file = compose_artifact_uri.rsplit("/", 1)[-1]
    compose_path = "{artifacts:path}/" + compose_file
    return {
        "RecipeFormatVersion": RECIPE_FORMAT_VERSION,
        "ComponentName": component_name,
        "ComponentVersion": version,
        "Manifests": [
            {
                "Platform": {"os": "linux"},
                "Artifacts": [{"URI": compose_artifact_uri}],
                "Lifecycle": {
                    "Run": "docker compose -f %s up -d" % compose_path,
                    "Shutdown": "docker compose -f %s down" % compose_path,
                },
            }
        ],
    }
