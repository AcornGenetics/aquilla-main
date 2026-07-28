"""Each image reports its own baked build provenance (#351).

The point of baking rather than injecting: an env var like RUNNING_IMAGE_DIGEST
is a claim made by whoever started the container — and /update/apply writes it
BEFORE triggering the swap, so it records intent, not outcome. A value baked into
the image bytes cannot misreport what is actually running.
"""
import json
import pathlib
import re

import pytest

from aquila_web import main

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_health_reports_build_identity(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    for key in ("app_version", "git_sha", "build_time", "running_image_digest"):
        assert key in body, f"/health must report {key}"


def test_health_still_reports_ok(client):
    """It is the Docker HEALTHCHECK target — the contract must not regress."""
    assert client.get("/health").json()["status"] == "ok"


def test_app_version_still_matches_the_config_file(client):
    """#340 made version.json the single source; #351 only adds keys to it."""
    expected = json.loads((REPO_ROOT / "config_files" / "version.json").read_text())["app_version"]
    assert client.get("/health").json()["app_version"] == expected
    assert client.get("/version").json()["version"] == expected


def test_identity_tolerates_an_image_built_before_this_change(tmp_path, monkeypatch):
    """Older images have only app_version. A device running one must not crash."""
    cfg = tmp_path / "config_files"
    cfg.mkdir()
    (cfg / "version.json").write_text('{"app_version": "2.1.0.5"}')
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)

    identity = main._read_build_identity()
    assert identity["app_version"] == "2.1.0.5"
    assert identity["git_sha"] == "unknown"
    assert identity["build_time"] == "unknown"


def test_identity_tolerates_a_missing_or_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    identity = main._read_build_identity()
    assert identity == {"app_version": "unknown", "git_sha": "unknown", "build_time": "unknown"}

    cfg = tmp_path / "config_files"
    cfg.mkdir()
    (cfg / "version.json").write_text("{ not json")
    assert main._read_build_identity()["git_sha"] == "unknown"


def test_identity_reads_the_baked_values(tmp_path, monkeypatch):
    cfg = tmp_path / "config_files"
    cfg.mkdir()
    (cfg / "version.json").write_text(json.dumps({
        "app_version": "2.1.0.5",
        "git_sha": "a1b2c3d4",
        "build_time": "2026-07-28T12:00:00Z",
    }))
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    identity = main._read_build_identity()
    assert identity["git_sha"] == "a1b2c3d4"
    assert identity["build_time"] == "2026-07-28T12:00:00Z"


# ── The delivery path has to be right, or the check compares an image to itself ──

def test_nginx_serves_version_json_locally():
    """Without an explicit location block, /version.json falls through to the
    catch-all proxy and is answered by the API container — so the UI would appear
    to match itself no matter how far the two images had drifted."""
    conf = (REPO_ROOT / "docker" / "nginx.conf").read_text()
    assert re.search(r"location\s*=\s*/version\.json", conf), (
        "nginx.conf must serve /version.json locally, not proxy it to the backend"
    )
    # And it must come before the catch-all, or nginx never reaches it.
    assert conf.index("/version.json") < conf.rindex("location / {")


@pytest.mark.parametrize("dockerfile", ["Dockerfile.api", "Dockerfile.ui"])
def test_both_images_accept_the_build_args(dockerfile):
    text = (REPO_ROOT / "docker" / dockerfile).read_text()
    assert "ARG GIT_SHA" in text
    assert "ARG BUILD_TIME" in text


@pytest.mark.parametrize("dockerfile", ["Dockerfile.api", "Dockerfile.ui"])
def test_both_images_carry_an_oci_revision_label(dockerfile):
    """#352 reads this from the registry manifest to resolve a digest back to a
    build, without pulling the image."""
    text = (REPO_ROOT / "docker" / dockerfile).read_text()
    assert "org.opencontainers.image.revision" in text


def test_ci_passes_the_build_args_to_both_images():
    wf = (REPO_ROOT / ".github" / "workflows" / "docker-build.yml").read_text()
    assert wf.count("GIT_SHA=${{ github.sha }}") == 2, "both api and ui builds"
    assert wf.count("BUILD_TIME=${{ env.BUILD_TIME }}") == 2
    assert "BUILD_TIME=$(date -u" in wf, (
        "computed in a step — github.event.head_commit is absent on workflow_dispatch"
    )
