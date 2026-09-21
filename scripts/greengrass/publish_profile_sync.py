"""Emit the pinned compose + Greengrass recipe for com.acorn.profile-sync (ADR-022).

Its own component, but it REUSES the aquilla-main-api image (same ECR digest the app
uses — already device-cached, no second image, no new ECR repo). It runs the sync
agent (`python -m aquila_web.profile_sync_main`) with network_mode: host so boto3 can
reach the Token Exchange Role creds endpoint on the host loopback.

Pure functions + a thin CLI; no AWS calls (the workflow does the upload + publish).
"""
import argparse
import copy
import json
from pathlib import Path

import yaml

from scripts.greengrass.recipe import RECIPE_FORMAT_VERSION

COMPONENT_NAME = "com.acorn.profile-sync"


def pin_compose(compose, api_ref):
    """Pin the profile-sync service to the exact api image digest (no build on-device)."""
    pinned = copy.deepcopy(compose)
    pinned["services"]["profile-sync"]["image"] = api_ref
    pinned["services"]["profile-sync"].pop("build", None)
    return pinned


def build_recipe(version, compose_artifact_uri, api_ref):
    """The Greengrass recipe for the profile-sync component.

    A docker component that reuses the api image (pinned by digest) and runs the sync
    agent with host networking. Depends on DockerApplicationManager (pre-pull),
    TokenExchangeService (S3 creds), and ShadowManager (the profiles shadow). Reads
    the shadow + writes reported over IPC — recipe vars are NOT interpolated inside
    accessControl resources, so the resource is "*" (the component only ever touches
    its own core device's shadow).
    """
    compose_file = compose_artifact_uri.rsplit("/", 1)[-1]
    compose_path = "{artifacts:path}/" + compose_file
    return {
        "RecipeFormatVersion": RECIPE_FORMAT_VERSION,
        "ComponentName": COMPONENT_NAME,
        "ComponentVersion": version,
        "ComponentDescription": (
            "Profile Sync Agent (ADR-022): reconciles /opt/aquila/profiles/managed "
            "from the profiles shadow + S3, read-only, on startup + delta + interval."
        ),
        "ComponentPublisher": "Acorn",
        "ComponentConfiguration": {
            "DefaultConfiguration": {
                "accessControl": {
                    "aws.greengrass.ShadowManager": {
                        COMPONENT_NAME + ":shadow:1": {
                            "policyDescription": "Read the profiles shadow; write reported.",
                            "operations": [
                                "aws.greengrass#GetThingShadow",
                                "aws.greengrass#UpdateThingShadow",
                            ],
                            "resources": ["*"],
                        }
                    },
                    # Subscribing to the shadow delta rides local pub/sub on the
                    # reserved delta topic. VERIFY on-device (#468): if denied, the
                    # interval backstop still syncs — deltas just aren't instant.
                    "aws.greengrass.ipc.pubsub": {
                        COMPONENT_NAME + ":pubsub:1": {
                            "policyDescription": "Receive profiles shadow delta events.",
                            "operations": ["aws.greengrass#SubscribeToTopic"],
                            "resources": [
                                "$aws/things/+/shadow/name/profiles/update/delta"
                            ],
                        }
                    },
                }
            }
        },
        "ComponentDependencies": {
            "aws.greengrass.DockerApplicationManager": {"VersionRequirement": ">=2.0.0"},
            "aws.greengrass.TokenExchangeService": {"VersionRequirement": ">=2.0.0"},
            "aws.greengrass.ShadowManager": {"VersionRequirement": ">=2.0.0"},
        },
        "Manifests": [
            {
                "Platform": {"os": "linux"},
                "Artifacts": [
                    {"URI": compose_artifact_uri},
                    # Pre-pull the api image (same digest the app uses → cached).
                    {"URI": "docker:" + api_ref},
                ],
                "Lifecycle": {
                    # Export the thing name (Greengrass sets SVCUID + the socket path +
                    # the TES cred vars in this process env; compose passes them through).
                    # `up` foreground keeps the component RUNNING tied to the container.
                    "Run": (
                        'export AWS_IOT_THING_NAME="{iot:thingName}"; '
                        + "docker compose -f %s up" % compose_path
                    ),
                    "Shutdown": "docker compose -f %s down" % compose_path,
                },
            }
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Emit pinned compose + recipe for profile-sync.")
    p.add_argument("--compose", required=True, help="source profile-sync-compose.yaml")
    p.add_argument("--api-ref", required=True, help="ECR digest ref for the api image")
    p.add_argument("--version", required=True)
    p.add_argument("--artifact-uri", required=True, help="s3:// URI of the compose artifact")
    p.add_argument("--out-compose", required=True)
    p.add_argument("--out-recipe", required=True)
    args = p.parse_args(argv)

    compose = yaml.safe_load(Path(args.compose).read_text())
    Path(args.out_compose).write_text(
        yaml.safe_dump(pin_compose(compose, args.api_ref), sort_keys=False)
    )
    recipe = build_recipe(args.version, args.artifact_uri, args.api_ref)
    Path(args.out_recipe).write_text(json.dumps(recipe, indent=2))


if __name__ == "__main__":
    main()
