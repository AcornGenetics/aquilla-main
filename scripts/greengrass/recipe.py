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
    # backend and app run the api image; ui runs the ui image. Only touch the
    # services a given compose actually defines.
    refs = {"backend": api_ref, "app": api_ref, "ui": ui_ref}
    for service, ref in refs.items():
        if service in pinned["services"]:
            pinned["services"][service]["image"] = ref
            pinned["services"][service].pop("build", None)
    return pinned


def build_recipe(component_name, version, compose_artifact_uri, image_refs=None):
    """Return the Greengrass recipe for a published component version.

    ``image_refs`` are the ECR digest refs of the app images; when given, the
    recipe depends on DockerApplicationManager so Greengrass pre-stages them.
    """
    compose_file = compose_artifact_uri.rsplit("/", 1)[-1]
    compose_path = "{artifacts:path}/" + compose_file
    # The compose file plus one docker: artifact per app image so
    # DockerApplicationManager pre-pulls them from ECR before the stack runs.
    artifacts = [{"URI": compose_artifact_uri}]
    for ref in image_refs or []:
        artifacts.append({"URI": "docker:" + ref})
    recipe = {
        "RecipeFormatVersion": RECIPE_FORMAT_VERSION,
        "ComponentName": component_name,
        "ComponentVersion": version,
        # Greengrass pulls/pre-stages the ECR images (via the device's token
        # exchange creds) before the compose stack runs.
        "ComponentDependencies": {
            "aws.greengrass.DockerApplicationManager": {
                "VersionRequirement": ">=2.0.0",
            },
        },
        "Manifests": [
            {
                "Platform": {"os": "linux"},
                "Artifacts": artifacts,
                "Lifecycle": {
                    # Bring the stack up, then foreground a /health monitor: while
                    # the app is healthy the component stays RUNNING; when /health
                    # fails the loop exits non-zero and Greengrass marks the
                    # component broken (feeds rollback in af#4).
                    "Run": (
                        "docker compose -f %s up -d && "
                        "while curl -fsS http://localhost:8090/health >/dev/null; "
                        "do sleep 30; done; exit 1" % compose_path
                    ),
                    "Shutdown": "docker compose -f %s down" % compose_path,
                },
            }
        ],
    }
    return recipe
