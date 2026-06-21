"""
D3 — Image-path agreement (rebrand #187, ADR-015).

After the repo rename, CI publishes `ghcr.io/acorngenetics/sentri-{api,ui}`
(derived from $GITHUB_REPOSITORY). The hardcoded compose/Dockerfile defaults do
NOT follow the rename automatically, so a device without an explicit GHCR_REPO
would resolve the wrong (frozen) image path. These tests pin the durable target.
"""
import re
from pathlib import Path

IMAGE_DEFAULT_FILES = [
    Path("fleet-config/docker-compose.yml"),
    Path("docker/docker-compose.yml"),
    Path("docker/Dockerfile.test"),
]
CI_FILES = [
    Path(".github/workflows/docker-build.yml"),
    Path(".github/workflows/promote-images.yml"),
]

# ghcr.io/${GHCR_REPO:-<default>}-api  -> capture <default>
DEFAULT_RE = re.compile(r"ghcr\.io/\$\{GHCR_REPO:-([^}]+)\}")


def test_compose_image_defaults_are_sentri():
    bad = []
    for f in IMAGE_DEFAULT_FILES:
        if not f.exists():
            continue
        for default in DEFAULT_RE.findall(f.read_text()):
            if default != "acorngenetics/sentri":
                bad.append(f"{f}: {default}")
    assert not bad, "image default(s) not 'acorngenetics/sentri':\n" + "\n".join(f"  - {b}" for b in bad)


def test_ci_derives_image_path_from_github_repository():
    for f in CI_FILES:
        if not f.exists():
            continue
        text = f.read_text()
        assert "GITHUB_REPOSITORY" in text, f"{f} should derive the image path from $GITHUB_REPOSITORY"
        # The only allowed mention of the old repo is the TEMPORARY dual-publish
        # path (removed in #188). If it appears, the removal marker must too.
        if "aquilla-main" in text:
            assert "#188" in text, (
                f"{f} references the old repo 'aquilla-main' without the dual-publish "
                f"removal marker (#188) — looks like a stale hardcoded path, not the "
                f"temporary cutover dual-publish"
            )
