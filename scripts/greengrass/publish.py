"""CLI glue for the component-publish workflow.

Reads the authored compose, pins it to the freshly-built image digests, and
emits the Greengrass recipe pointing at the compose artifact in S3. All the
artifact-shaping logic is the tested pure functions in ``recipe.py`` — this only
does argument plumbing and file IO, so the workflow can call one command.

Run from the repo root:  python -m scripts.greengrass.publish --help
"""
import argparse
import json
from pathlib import Path

import yaml

from scripts.greengrass.recipe import build_recipe, pin_compose


def main(argv=None):
    p = argparse.ArgumentParser(description="Emit pinned compose + Greengrass recipe.")
    p.add_argument("--compose", required=True, help="source compose.yaml")
    p.add_argument("--api-ref", required=True, help="ECR digest ref for the api image")
    p.add_argument("--ui-ref", required=True, help="ECR digest ref for the ui image")
    p.add_argument("--component-name", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--artifact-uri", required=True, help="s3:// URI of the compose artifact")
    p.add_argument(
        "--prune-artifact-uri",
        help="s3:// URI of the image-retention script (#397); omit to publish without it",
    )
    p.add_argument("--out-compose", required=True, help="write the pinned compose here")
    p.add_argument("--out-recipe", required=True, help="write the recipe JSON here")
    args = p.parse_args(argv)

    compose = yaml.safe_load(Path(args.compose).read_text())
    pinned = pin_compose(compose, args.api_ref, args.ui_ref)
    Path(args.out_compose).write_text(yaml.safe_dump(pinned, sort_keys=False))

    recipe = build_recipe(
        args.component_name,
        args.version,
        args.artifact_uri,
        image_refs=[args.api_ref, args.ui_ref],
        prune_artifact_uri=args.prune_artifact_uri,
    )
    Path(args.out_recipe).write_text(json.dumps(recipe, indent=2))


if __name__ == "__main__":
    main()
