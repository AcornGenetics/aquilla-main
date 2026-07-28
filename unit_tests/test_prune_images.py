"""Image retention / rollback logic for scripts/deploy/prune-images.sh (#355).

A device keeps at most two sets, both from its current ring: the image it runs
(ring-tagged) and the build it replaced (untagged). A ring change deletes every
old-ring image and leaves no fallback.

The script cannot be imported, so each test builds a fake `docker` on PATH that
answers the few subcommands it uses. That keeps the real logic under test —
classification, ordering, the ring-change branch — without needing Docker or a
device.

Hardware note: "never remove an image a container references" is enforced by
`docker rmi` refusing, not by the script, so it cannot be exercised here. It is
covered by the on-device check in deployment2_verify.sh.
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy" / "prune-images.sh"
REPO = "ghcr.io/acorngenetics/aquilla-main"

API_WORKDIR = "/opt/aquila"
UI_CMD = '["nginx","-g","daemon off;"]'


def _fake_docker(tmp_path, untagged, tagged):
    """Stub `docker` on PATH.

    ``untagged`` maps image id -> (kind, created); kind is "api", "ui" or "other".
    ``tagged`` is a list of full refs, e.g. f"{REPO}-api:pilot".
    Removals are appended to removed.txt for assertions.

    The stub reads TSV data files rather than having tables generated into its
    source — embedding shell-quoted JSON in generated `case` branches is fragile
    enough to produce false failures.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    rows = []
    for img_id, (kind, created) in untagged.items():
        workdir = API_WORKDIR if kind == "api" else "/"
        cmd = {"ui": UI_CMD, "api": '["uvicorn"]'}.get(kind, '["sleep"]')
        rows.append(f"{img_id}\t{workdir}\t{cmd}\t{created}")
    data = tmp_path / "images.tsv"
    data.write_text("\n".join(rows) + ("\n" if rows else ""))

    tags = tmp_path / "tags.txt"
    tags.write_text("\n".join(tagged or []) + ("\n" if tagged else ""))

    script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        DATA="{data}"
        TAGS="{tags}"
        field() {{ awk -F'\\t' -v id="$1" -v n="$2" '$1==id {{print $n}}' "$DATA"; }}
        case "$1" in
          images)
            case "$*" in
              *Repository*) cat "$TAGS" ;;
              *)            cut -f1 "$DATA" ;;
            esac
            ;;
          inspect)
            case "$*" in
              *WorkingDir*) field "$2" 2 ;;
              *Config.Cmd*) field "$2" 3 ;;
              *Created*)    field "$2" 4 ;;
            esac
            ;;
          rmi) echo "$2" >> "{tmp_path}/removed.txt" ;;
        esac
        exit 0
        """
    )
    (bin_dir / "docker").write_text(script)
    (bin_dir / "docker").chmod(0o755)
    return bin_dir


def _run(tmp_path, untagged=None, tagged=None, ring="pilot", last_ring=None, **env):
    bin_dir = _fake_docker(tmp_path, untagged or {}, tagged or [])

    fleet_env = tmp_path / "fleet.env"
    fleet_env.write_text(f"IMAGE_TAG={ring}\n" if ring else "")

    state = tmp_path / "prune-state"
    if last_ring:
        state.write_text(f"{last_ring}\n")
    elif state.exists():
        state.unlink()

    (tmp_path / "removed.txt").unlink(missing_ok=True)

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FLEET_ENV": str(fleet_env),
            "DEVICE_ENV": str(tmp_path / "nonexistent.env"),
            "STATE_FILE": str(state),
            **env,
        },
    )
    removed_file = tmp_path / "removed.txt"
    removed = removed_file.read_text().split() if removed_file.exists() else []
    return result, removed


# ── Same-ring updates ─────────────────────────────────────────────────────────

def test_same_ring_update_keeps_current_plus_one_fallback(tmp_path):
    """Deploy pilot v3: current=v3 (tagged), fallback=v2, v1 removed."""
    untagged = {
        "pilot_v1": ("api", "2026-07-01T00:00:00Z"),
        "pilot_v2": ("api", "2026-07-02T00:00:00Z"),
    }
    result, removed = _run(
        tmp_path, untagged, tagged=[f"{REPO}-api:pilot"], ring="pilot", last_ring="pilot"
    )
    assert result.returncode == 0, result.stderr
    assert removed == ["pilot_v1"], "only the older fallback should go"


def test_same_ring_keeps_exactly_one_fallback_per_family(tmp_path):
    """A spare API image with no matching UI image would roll back to nothing."""
    untagged = {
        "api_old": ("api", "2026-07-01T00:00:00Z"),
        "api_new": ("api", "2026-07-02T00:00:00Z"),
        "ui_old": ("ui", "2026-07-01T00:00:00Z"),
        "ui_new": ("ui", "2026-07-02T00:00:00Z"),
    }
    _, removed = _run(tmp_path, untagged, ring="pilot", last_ring="pilot")
    assert sorted(removed) == ["api_old", "ui_old"]


def test_fallback_chosen_by_creation_date(tmp_path):
    untagged = {
        "middle": ("api", "2026-07-02T00:00:00Z"),
        "newest": ("api", "2026-07-03T00:00:00Z"),
        "oldest": ("api", "2026-07-01T00:00:00Z"),
    }
    _, removed = _run(tmp_path, untagged, ring="pilot", last_ring="pilot")
    assert "newest" not in removed
    assert sorted(removed) == ["middle", "oldest"]


# ── Ring changes ──────────────────────────────────────────────────────────────

def test_ring_change_removes_all_old_ring_images_and_keeps_no_fallback(tmp_path):
    """Promote pilot -> prod: pilot v3 and v2 both go, prod v1 has no fallback."""
    untagged = {
        "pilot_v2": ("api", "2026-07-02T00:00:00Z"),
        "pilot_v3": ("api", "2026-07-03T00:00:00Z"),
    }
    tagged = [f"{REPO}-api:pilot", f"{REPO}-api:prod"]
    result, removed = _run(tmp_path, untagged, tagged, ring="prod", last_ring="pilot")
    assert result.returncode == 0, result.stderr
    assert "pilot_v2" in removed and "pilot_v3" in removed, "no fallback survives a ring change"
    assert f"{REPO}-api:pilot" in removed, "the old ring tag goes too"
    assert f"{REPO}-api:prod" not in removed, "the new current image must survive"


def test_first_run_with_no_state_is_treated_as_a_ring_change(tmp_path):
    """An unverifiable fallback is not a fallback; establish a clean baseline."""
    untagged = {"unknown_origin": ("api", "2026-07-02T00:00:00Z")}
    result, removed = _run(tmp_path, untagged, ring="pilot", last_ring=None)
    assert removed == ["unknown_origin"]
    assert "no previous state" in result.stdout


def test_ring_is_recorded_so_the_next_run_can_tell(tmp_path):
    _run(tmp_path, ring="prod", last_ring="pilot")
    assert (tmp_path / "prune-state").read_text().strip() == "prod"


def test_dry_run_does_not_write_state(tmp_path):
    """A dry run must not make the next real run think the ring was unchanged."""
    result, removed = _run(tmp_path, ring="prod", last_ring="pilot", DRY_RUN="1")
    assert removed == []
    assert not (tmp_path / "prune-state").read_text().strip() == "prod"
    assert "state not written" in result.stdout


# ── Foreign and non-ring tags ─────────────────────────────────────────────────

def test_removes_tags_for_rings_the_device_is_not_on(tmp_path):
    tagged = [f"{REPO}-api:dev", f"{REPO}-api:pilot", f"{REPO}-ui:dev", f"{REPO}-ui:pilot"]
    _, removed = _run(tmp_path, tagged=tagged, ring="pilot", last_ring="pilot")
    assert sorted(removed) == sorted([f"{REPO}-api:dev", f"{REPO}-ui:dev"])


def test_removes_latest_which_is_not_a_ring(tmp_path):
    """No device should run :latest — it tracks whatever was built last."""
    tagged = [f"{REPO}-api:latest", f"{REPO}-api:sandbox"]
    _, removed = _run(tmp_path, tagged=tagged, ring="sandbox", last_ring="sandbox")
    assert removed == [f"{REPO}-api:latest"]


def test_never_touches_non_aquila_images(tmp_path):
    """Watchtower and the dead telemetry images must survive."""
    tagged = [
        "nickfedor/watchtower:latest",
        "timberio/vector:0.33.1-alpine",
        "prom/node-exporter:latest",
        "victoriametrics/vmagent:latest",
    ]
    untagged = {f"other{i}": ("other", f"2026-01-0{i}T00:00:00Z") for i in range(1, 5)}
    _, removed = _run(tmp_path, untagged, tagged, ring="pilot", last_ring="pilot")
    assert removed == []


# ── Safety ────────────────────────────────────────────────────────────────────

def test_unknown_ring_removes_nothing(tmp_path):
    """Never guess the ring — guessing wrong deletes the running image's fallback."""
    untagged = {"api1": ("api", "2026-07-01T00:00:00Z")}
    tagged = [f"{REPO}-api:dev"]
    result, removed = _run(tmp_path, untagged, tagged, ring=None)
    assert result.returncode == 0
    assert removed == []
    assert "will not guess" in result.stdout


def test_no_images_is_not_an_error(tmp_path):
    result, removed = _run(tmp_path, ring="pilot", last_ring="pilot")
    assert result.returncode == 0
    assert removed == []


# ── The worked example from the spec ──────────────────────────────────────────

def test_full_lifecycle_matches_the_spec(tmp_path):
    """Pilot v1->v2->v3, promote to prod, then prod v1->v2->v3."""
    api_pilot, api_prod = f"{REPO}-api:pilot", f"{REPO}-api:prod"

    # Deploy pilot v2 — v1 becomes the fallback, nothing to delete yet.
    _, removed = _run(
        tmp_path, {"v1": ("api", "2026-07-01T00:00:00Z")},
        [api_pilot], ring="pilot", last_ring="pilot",
    )
    assert removed == []

    # Deploy pilot v3 — v2 becomes the fallback, v1 goes.
    _, removed = _run(
        tmp_path,
        {"v1": ("api", "2026-07-01T00:00:00Z"), "v2": ("api", "2026-07-02T00:00:00Z")},
        [api_pilot], ring="pilot", last_ring="pilot",
    )
    assert removed == ["v1"]

    # Promote to prod — every pilot image goes, no fallback.
    _, removed = _run(
        tmp_path,
        {"v2": ("api", "2026-07-02T00:00:00Z"), "v3": ("api", "2026-07-03T00:00:00Z")},
        [api_pilot, api_prod], ring="prod", last_ring="pilot",
    )
    assert sorted(removed) == sorted(["v2", "v3", api_pilot])

    # Deploy prod v2 — prod v1 becomes the fallback.
    _, removed = _run(
        tmp_path, {"prod_v1": ("api", "2026-07-04T00:00:00Z")},
        [api_prod], ring="prod", last_ring="prod",
    )
    assert removed == []

    # Deploy prod v3 — prod v2 is the fallback, prod v1 goes.
    _, removed = _run(
        tmp_path,
        {"prod_v1": ("api", "2026-07-04T00:00:00Z"), "prod_v2": ("api", "2026-07-05T00:00:00Z")},
        [api_prod], ring="prod", last_ring="prod",
    )
    assert removed == ["prod_v1"]


# ── entrypoint sync ───────────────────────────────────────────────────────────
# The script reaches a device by riding in the container image: entrypoint.sh
# copies it to /opt/fleet, which is bind-mounted from the host. That is the only
# automatic delivery path — nothing on a device fetches host-side scripts.

ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker" / "entrypoint.sh"


def _run_entrypoint(tmp_path, fleet_dir, make_writable=True):
    helper_src = tmp_path / "opt" / "aquila" / "scripts" / "deploy"
    helper_src.mkdir(parents=True, exist_ok=True)
    (helper_src / "prune-images.sh").write_text("#!/usr/bin/env bash\necho stub\n")

    fleet_dir.mkdir(parents=True, exist_ok=True)
    if not make_writable:
        fleet_dir.chmod(0o500)

    src = ENTRYPOINT.read_text().replace(
        'helper_src="/opt/aquila/scripts/deploy"', f'helper_src="{helper_src}"'
    )
    patched = tmp_path / "entrypoint.sh"
    patched.write_text(src)
    patched.chmod(0o755)

    return subprocess.run(
        ["bash", str(patched), "true"],
        capture_output=True,
        text=True,
        env={**os.environ, "FLEET_DIR": str(fleet_dir), "PROFILE_DIR": str(tmp_path / "profiles")},
    )


def test_entrypoint_syncs_prune_script_to_fleet_dir(tmp_path):
    fleet = tmp_path / "fleet"
    result = _run_entrypoint(tmp_path, fleet)
    assert result.returncode == 0, result.stderr
    synced = fleet / "prune-images.sh"
    assert synced.exists()
    assert os.access(synced, os.X_OK)


def test_entrypoint_overwrites_an_older_copy(tmp_path):
    """A device holding an old copy must get the new one on restart."""
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    (fleet / "prune-images.sh").write_text("#!/usr/bin/env bash\necho STALE\n")
    _run_entrypoint(tmp_path, fleet)
    assert "STALE" not in (fleet / "prune-images.sh").read_text()


def test_entrypoint_survives_missing_fleet_mount(tmp_path):
    """/opt/fleet is mounted into backend only — a no-op in the app container."""
    result = _run_entrypoint(tmp_path, tmp_path / "does-not-exist")
    assert result.returncode == 0, result.stderr


def test_entrypoint_survives_readonly_fleet_mount(tmp_path):
    result = _run_entrypoint(tmp_path, tmp_path / "ro-fleet", make_writable=False)
    (tmp_path / "ro-fleet").chmod(0o700)  # restore so pytest can clean up
    assert result.returncode == 0, result.stderr
