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
        # Authorize the Device-Shadow IPC ops the update agent uses. Without this
        # policy ShadowManager denies UpdateThingShadow and publish_health() fails
        # (the shadow stays dark — #395). NOTE: recipe variables like {iot:thingName}
        # are NOT interpolated inside accessControl resources, so a scoped
        # "$aws/things/{iot:thingName}/shadow" never matches and is denied. The
        # resource must be "*" — the component only ever writes its own core
        # device's shadow, so this stays effectively the device's own shadow.
        "ComponentConfiguration": {
            "DefaultConfiguration": {
                "accessControl": {
                    "aws.greengrass.ShadowManager": {
                        component_name + ":shadow:1": {
                            "policyDescription": (
                                "Read/write this core device's own shadow"
                            ),
                            "operations": [
                                "aws.greengrass#GetThingShadow",
                                "aws.greengrass#UpdateThingShadow",
                            ],
                            "resources": ["*"],
                        }
                    }
                }
            }
        },
        # Greengrass pulls/pre-stages the ECR images (via the device's token
        # exchange creds) before the compose stack runs. TokenExchangeService is
        # what mints those creds from the device cert — required for private ECR,
        # and as a dependency it ships with every deployment (no per-ring add).
        "ComponentDependencies": {
            "aws.greengrass.DockerApplicationManager": {
                "VersionRequirement": ">=2.0.0",
            },
            "aws.greengrass.TokenExchangeService": {
                "VersionRequirement": ">=2.0.0",
            },
            # Services the Device-Shadow IPC ops the update agent uses (am#382/#395)
            # — publishing running SHAs + Container Health. As a recipe dependency it
            # ships with every deployment; the deployment configures it to sync the
            # core device's classic shadow to the cloud.
            "aws.greengrass.ShadowManager": {
                "VersionRequirement": ">=2.0.0",
            },
        },
        "Manifests": [
            {
                "Platform": {"os": "linux"},
                "Artifacts": artifacts,
                "Lifecycle": {
                    # Bring the stack up, wait out a startup buffer (the backend
                    # takes ~15s to boot, so checking immediately would flap the
                    # component BROKEN), then foreground a /health monitor: while
                    # the app is healthy the component stays RUNNING; when /health
                    # fails the loop exits non-zero and Greengrass marks it broken
                    # (feeds rollback in af#4).
                    "Run": (
                        # Give the containers this core device's thing name so the
                        # update agent (am#382) can address its own Device Shadow
                        # over IPC. SVCUID + the nucleus socket path are already in
                        # this process env (Greengrass sets them) and compose passes
                        # them through; the thing name is not, so export it here.
                        'export AWS_IOT_THING_NAME="{iot:thingName}"; '
                        "docker compose -f %s up -d; "
                        # buffer: do not check /health for the first 25s (boot ~15s)
                        "sleep 25; "
                        # grace: then poll up to ~1 min for the first healthy response
                        "for i in $(seq 1 12); do "
                        "curl -fsS http://localhost:8090/health >/dev/null 2>&1 && break; "
                        "sleep 5; done; "
                        # monitor: stay RUNNING while healthy; exit non-zero when it fails
                        "while curl -fsS http://localhost:8090/health >/dev/null 2>&1; "
                        "do sleep 30; done; exit 1" % compose_path
                    ),
                    "Shutdown": "docker compose -f %s down" % compose_path,
                },
            }
        ],
    }
    return recipe
