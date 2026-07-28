"""Retention logic for scripts/deploy/prune-images.sh (#355).

The script cannot be imported, so each test builds a fake `docker` executable on
PATH that answers the handful of subcommands the script uses. That keeps the
real retention logic under test — classification, ordering, the keep-count —
without needing Docker or a device.

Hardware note: the script's rule 1 ("never remove an image a container
references") is enforced by `docker rmi` refusing, not by the script, so it
cannot be exercised here. It is covered by the on-device check in
deployment2_verify.sh.
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy" / "prune-images.sh"

API_WORKDIR = "/opt/aquila"
UI_CMD = '["nginx","-g","daemon off;"]'


def _fake_docker(tmp_path, images):
    """Write a stub `docker` onto PATH.

    ``images`` maps image id -> (kind, created), where kind is "api", "ui" or
    "other". Removals are appended to removed.txt so a test can assert on them.

    The stub reads a TSV data file rather than having the table generated into
    its source — embedding shell-quoted JSON in generated `case` branches is
    fragile enough to produce false failures.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    rows = []
    for img_id, (kind, created) in images.items():
        workdir = API_WORKDIR if kind == "api" else "/"
        cmd = {"ui": UI_CMD, "api": '["uvicorn"]'}.get(kind, '["sleep"]')
        rows.append(f"{img_id}\t{workdir}\t{cmd}\t{created}")
    data = tmp_path / "images.tsv"
    data.write_text("\n".join(rows) + ("\n" if rows else ""))

    script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        DATA="{data}"
        field() {{ awk -F'\\t' -v id="$1" -v n="$2" '$1==id {{print $n}}' "$DATA"; }}
        case "$1" in
          images) cut -f1 "$DATA" ;;
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


def _run(tmp_path, images, **env):
    bin_dir = _fake_docker(tmp_path, images)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", **env},
    )
    removed_file = tmp_path / "removed.txt"
    removed = removed_file.read_text().split() if removed_file.exists() else []
    return result, removed


def test_keeps_two_previous_api_images_by_default(tmp_path):
    """Default IMAGE_RETENTION_SETS=3 means the running (tagged) set plus 2 previous."""
    images = {
        "api1": ("api", "2026-07-20T00:00:00Z"),
        "api2": ("api", "2026-07-21T00:00:00Z"),
        "api3": ("api", "2026-07-22T00:00:00Z"),
        "api4": ("api", "2026-07-23T00:00:00Z"),
    }
    result, removed = _run(tmp_path, images)
    assert result.returncode == 0, result.stderr
    # newest two (api4, api3) survive; the older two go
    assert sorted(removed) == ["api1", "api2"]


def test_removes_oldest_first(tmp_path):
    """Ordering is by created time, not by id or docker's listing order."""
    images = {
        "newest": ("api", "2026-07-25T00:00:00Z"),
        "oldest": ("api", "2026-01-01T00:00:00Z"),
        "middle": ("api", "2026-07-01T00:00:00Z"),
    }
    _, removed = _run(tmp_path, images)
    assert removed == ["oldest"]


def test_api_and_ui_counted_separately(tmp_path):
    """3 API sets and 3 UI sets, not 3 images total."""
    images = {
        "api1": ("api", "2026-07-20T00:00:00Z"),
        "api2": ("api", "2026-07-21T00:00:00Z"),
        "ui1": ("ui", "2026-07-20T00:00:00Z"),
        "ui2": ("ui", "2026-07-21T00:00:00Z"),
    }
    _, removed = _run(tmp_path, images)
    # two of each is exactly the limit — nothing should be removed
    assert removed == []


def test_never_touches_unrecognised_images(tmp_path):
    """Watchtower and anything else must never be a candidate."""
    images = {
        "other1": ("other", "2026-01-01T00:00:00Z"),
        "other2": ("other", "2026-01-02T00:00:00Z"),
        "other3": ("other", "2026-01-03T00:00:00Z"),
        "other4": ("other", "2026-01-04T00:00:00Z"),
    }
    _, removed = _run(tmp_path, images)
    assert removed == []


def test_dry_run_removes_nothing(tmp_path):
    images = {f"api{i}": ("api", f"2026-07-2{i}T00:00:00Z") for i in range(1, 5)}
    result, removed = _run(tmp_path, images, DRY_RUN="1")
    assert result.returncode == 0
    assert removed == []
    assert "would remove" in result.stdout


def test_retention_count_is_configurable(tmp_path):
    """IMAGE_RETENTION_SETS=1 keeps only the running set, so all untagged go."""
    images = {f"api{i}": ("api", f"2026-07-2{i}T00:00:00Z") for i in range(1, 4)}
    _, removed = _run(tmp_path, images, IMAGE_RETENTION_SETS="1")
    assert sorted(removed) == ["api1", "api2", "api3"]


def test_no_dangling_images_is_not_an_error(tmp_path):
    result, removed = _run(tmp_path, {})
    assert result.returncode == 0
    assert removed == []


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "2.5"])
def test_rejects_invalid_retention_count(tmp_path, bad):
    """A typo'd value must fail loudly rather than silently deleting everything."""
    images = {"api1": ("api", "2026-07-20T00:00:00Z")}
    result, removed = _run(tmp_path, images, IMAGE_RETENTION_SETS=bad)
    assert result.returncode != 0
    assert removed == []


def test_empty_retention_count_falls_back_to_default(tmp_path):
    """`IMAGE_RETENTION_SETS=` in device.env means "use the default", not "abort"."""
    images = {f"api{i}": ("api", f"2026-07-2{i}T00:00:00Z") for i in range(1, 5)}
    result, removed = _run(tmp_path, images, IMAGE_RETENTION_SETS="")
    assert result.returncode == 0
    assert sorted(removed) == ["api1", "api2"]  # default of 3 -> keep 2 untagged
