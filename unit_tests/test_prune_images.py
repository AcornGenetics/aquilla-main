"""Image retention on a Greengrass device (#397).

The rule under test:

    keep any image a container references
    keep the newest image per repository
    delete everything else

These source scripts/greengrass/prune-images.sh and drive its shell functions with
synthetic image records, so the decision runs offline with no Docker daemon. Sourcing
is safe: the script only acts when executed, not when sourced.

Records are the format collect_images() produces:  <id>\\t<created>\\t<ref> [<ref>...]
"""
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path("scripts/greengrass/prune-images.sh")

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash required to exercise the shell functions"
)

ECR = "867958227555.dkr.ecr.us-east-2.amazonaws.com"


def _select(records: str, protected: str = "") -> list[str]:
    """Run select_removals over the given records; return the IDs it would remove.

    Records go in over stdin rather than embedded in the script: the fields are
    tab-separated, and interpolating them would pass Python's escaped ``\\t`` through
    as a literal backslash-t.
    """
    script = f"source {SCRIPT}\nselect_removals {protected!r}"
    result = subprocess.run(
        ["bash", "-c", script],
        input=records, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line]


def _repo_of(ref: str) -> str:
    result = subprocess.run(
        ["bash", "-c", f"source {SCRIPT}; repo_of {ref!r}"],
        capture_output=True, text=True, timeout=60,
    )
    return result.stdout.strip()


# --- repository parsing -----------------------------------------------------
# Grouping is by repository, so this parse is what the whole rule rests on.

@pytest.mark.parametrize(
    "ref,expected",
    [
        (f"{ECR}/aquilla-main-api:latest", f"{ECR}/aquilla-main-api"),
        (f"{ECR}/aquilla-main-api@sha256:abc123", f"{ECR}/aquilla-main-api"),
        ("ghcr.io/acorngenetics/aquilla-main-api:dev", "ghcr.io/acorngenetics/aquilla-main-api"),
        ("timberio/vector:0.33.1-alpine", "timberio/vector"),
        ("prom/node-exporter:latest", "prom/node-exporter"),
        ("", ""),
    ],
)
def test_repository_is_parsed_from_any_ref_shape(ref: str, expected: str) -> None:
    assert _repo_of(ref) == expected


def test_registry_port_is_not_mistaken_for_a_tag() -> None:
    """localhost:5000/img is a registry with a port, not a repo with tag '5000/img'."""
    assert _repo_of("localhost:5000/aquilla-main-api") == "localhost:5000/aquilla-main-api"


# --- the retention rule -----------------------------------------------------

def test_supersedes_the_previous_greengrass_image() -> None:
    """The measured case on sn01: two deployments, both ECR images still on disk.

    Greengrass pins by digest, so the superseded image keeps its repository and shows
    tag <none> — which docker does NOT treat as dangling, so the built-in prune leaves
    it. This is the accumulation the whole issue is about.
    """
    records = (
        f"new\t2026-08-03T09:35:43Z\t{ECR}/aquilla-main-api@sha256:new\n"
        f"old\t2026-07-31T17:52:10Z\t{ECR}/aquilla-main-api@sha256:old\n"
    )
    assert _select(records) == ["old"]


def test_keeps_an_image_a_container_uses_even_if_not_newest() -> None:
    """A running container must never lose its image, whatever the dates say."""
    records = (
        f"new\t2026-08-03T09:35:43Z\t{ECR}/aquilla-main-api@sha256:new\n"
        f"running\t2026-07-31T17:52:10Z\t{ECR}/aquilla-main-api@sha256:old\n"
    )
    assert _select(records, protected="running") == []


def test_removes_dangling_images() -> None:
    """No repository at all — the 4.85 GB of layer leftovers measured on sn01."""
    records = (
        f"kept\t2026-08-03T09:35:43Z\t{ECR}/aquilla-main-api:latest\n"
        "dangling1\t2026-07-01T00:00:00Z\t\n"
        "dangling2\t2026-06-01T00:00:00Z\t\n"
    )
    assert sorted(_select(records)) == ["dangling1", "dangling2"]


def test_protects_the_cert_renewal_image() -> None:
    """aquila-cert-renew.service runs a throwaway container once a day, so its image
    is unused for 23h59m and `docker image prune -a` would delete it. Losing it makes
    certificate renewal depend on a GHCR re-pull that may fail silently on a migrated
    device — until the cert expires and the device drops off the fleet.

    Being newest of its repository protects it, with no special-casing.
    """
    records = (
        f"ecr_new\t2026-08-03T09:35:43Z\t{ECR}/aquilla-main-api@sha256:new\n"
        f"ecr_old\t2026-07-31T17:52:10Z\t{ECR}/aquilla-main-api@sha256:old\n"
        "ghcr_cert\t2026-07-21T15:33:57Z\tghcr.io/acorngenetics/aquilla-main-api:dev\n"
    )
    removals = _select(records, protected="ecr_new")

    assert "ghcr_cert" not in removals, "cert renewal image must survive"
    assert removals == ["ecr_old"]


def test_each_repository_keeps_its_own_newest() -> None:
    """Repositories are independent — api and ui each keep one."""
    records = (
        f"api_new\t2026-08-03T09:35:43Z\t{ECR}/aquilla-main-api@sha256:a\n"
        f"api_old\t2026-07-31T17:52:10Z\t{ECR}/aquilla-main-api@sha256:b\n"
        f"ui_new\t2026-08-03T09:36:04Z\t{ECR}/aquilla-main-ui@sha256:c\n"
        f"ui_old\t2026-07-31T17:52:30Z\t{ECR}/aquilla-main-ui@sha256:d\n"
    )
    assert sorted(_select(records)) == ["api_old", "ui_old"]


def test_a_migrating_device_sheds_its_old_ghcr_images() -> None:
    """A device arriving from the Watchtower world carries ghcr.io images. Grouping is
    registry-agnostic, so ECR and GHCR are separate repositories and each keeps one —
    the stale GHCR *ui* image goes once a newer one exists in that same repository."""
    records = (
        f"ecr_api\t2026-08-03T09:35:43Z\t{ECR}/aquilla-main-ui@sha256:new\n"
        "ghcr_ui_new\t2026-07-21T15:34:43Z\tghcr.io/acorngenetics/aquilla-main-ui:dev\n"
        "ghcr_ui_old\t2026-05-01T10:00:00Z\tghcr.io/acorngenetics/aquilla-main-ui:dev\n"
    )
    assert _select(records) == ["ghcr_ui_old"]


def test_unrelated_images_are_kept_when_they_are_the_only_one() -> None:
    """timberio/vector (2023) and the retired monitoring stack are each the newest of
    their repository, so they survive. That is the price of not touching host files —
    one image per repository, rather than a rule that could delete the cert image."""
    records = (
        "vector\t2023-10-30T10:58:35Z\ttimberio/vector:0.33.1-alpine\n"
        "nodeexp\t2025-10-25T13:11:08Z\tprom/node-exporter:latest\n"
    )
    assert _select(records) == []


def test_an_image_with_several_tags_is_kept_once() -> None:
    """Same image, two names — it is newest in both repositories, kept either way."""
    records = (
        "multi\t2026-08-03T09:35:43Z\tghcr.io/x/api:dev ghcr.io/x/api:latest\n"
        "older\t2026-07-01T00:00:00Z\tghcr.io/x/api:old\n"
    )
    assert _select(records) == ["older"]


def test_nothing_is_removed_when_every_image_is_newest_or_in_use() -> None:
    records = f"only\t2026-08-03T09:35:43Z\t{ECR}/aquilla-main-api:latest\n"
    assert _select(records) == []


# --- reporting --------------------------------------------------------------

def test_reports_evaluated_count_when_nothing_is_removable() -> None:
    """'0 removable of 12' must be distinguishable from 'found nothing to evaluate'.
    A cleanup that silently stops matching anything is the failure nobody notices."""
    script = textwrap.dedent(f"""
        source {SCRIPT}
        collect_images() {{ printf 'a\t2026-08-03T09:35:43Z\tghcr.io/x/api:dev\\n'; }}
        protected_ids() {{ printf ''; }}
        main
    """)
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=60
    ).stdout

    assert "1 images, 0 removable" in out


def test_dry_run_removes_nothing() -> None:
    script = textwrap.dedent(f"""
        source {SCRIPT}
        DRY_RUN=1
        collect_images() {{
            printf 'new\t2026-08-03T09:35:43Z\tghcr.io/x/api:dev\\n'
            printf 'old\t2026-01-01T00:00:00Z\tghcr.io/x/api:old\\n'
        }}
        protected_ids() {{ printf ''; }}
        docker() {{ echo "DOCKER CALLED: $*"; }}
        main
    """)
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=60
    ).stdout

    assert "would remove old" in out
    assert "DOCKER CALLED: rmi" not in out, "dry run must not remove anything"


def test_a_failed_removal_is_reported_not_swallowed() -> None:
    """docker refuses to remove an image another image layers on. That is expected and
    must not abort the run, but it must be visible rather than counted as success."""
    script = textwrap.dedent(f"""
        source {SCRIPT}
        collect_images() {{
            printf 'new\t2026-08-03T09:35:43Z\tghcr.io/x/api:dev\\n'
            printf 'old\t2026-01-01T00:00:00Z\tghcr.io/x/api:old\\n'
        }}
        protected_ids() {{ printf ''; }}
        docker() {{ return 1; }}
        main
    """)
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=60
    )

    assert "could not remove old" in result.stdout
    assert "0 removed" in result.stdout
    assert result.returncode == 0, "a stuck image must not fail the deployment"


def test_dangling_images_are_enumerated() -> None:
    """Regression from hardware: `docker images -q` omits dangling images.

    Measured on sn01 (docker 29.7.0): 11 listed, 9 dangling, 20 total — and those 9
    held 4.85 GB of the 5.9 GB reclaimable. Collecting only the listed set silently
    ignored most of the problem while reporting success.
    """
    script = textwrap.dedent(f"""
        source {SCRIPT}
        docker() {{
            if [ "$1" = images ]; then
                case "$*" in
                    *dangling*) echo "sha_dangling" ;;
                    *--quiet*)  echo "sha_tagged" ;;
                esac
            elif [ "$1" = inspect ]; then
                shift 2   # drop `inspect --format <fmt>`
                for id in "$@"; do printf '%s\\t2026-01-01T00:00:00Z\\t\\n' "$id"; done
            fi
        }}
        collect_images | cut -f1 | sort
    """)
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=60
    ).stdout.split()

    assert "sha_dangling" in out, "dangling images must be collected"
    assert "sha_tagged" in out
