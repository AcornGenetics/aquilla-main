"""Publishing the host updater from the image to /opt/fleet (#357).

/opt/fleet/update.sh was previously written once at provisioning and never refreshed,
so a fix to it could only reach the fleet by hand. Syncing it on startup puts it on the
normal ring promotion path.

The failure modes here are unusually expensive: a truncated update.sh leaves a device
unable to update at all, and the only thing that could repair that remotely is the very
script being written. Hence the emphasis on atomicity and on never raising.
"""
import os
import stat

import pytest

from aquila_web.main import sync_fleet_update_script


@pytest.fixture
def src(tmp_path):
    path = tmp_path / "image" / "fleet-update.sh"
    path.parent.mkdir()
    path.write_text("#!/usr/bin/env bash\necho new\n")
    return path


def test_writes_the_script_when_the_host_has_none(src, tmp_path):
    dest = tmp_path / "fleet" / "update.sh"
    dest.parent.mkdir()

    assert sync_fleet_update_script(str(src), str(dest)) == "synced"
    assert dest.read_text() == src.read_text()


def test_replaces_an_outdated_host_script(src, tmp_path):
    """The case that matters: a device provisioned months ago on an old main."""
    dest = tmp_path / "update.sh"
    dest.write_text("#!/usr/bin/env bash\necho ancient\n")

    assert sync_fleet_update_script(str(src), str(dest)) == "synced"
    assert "new" in dest.read_text()


def test_is_executable_after_syncing(src, tmp_path):
    """It is invoked directly as /opt/fleet/update.sh, so the bit must be set."""
    dest = tmp_path / "update.sh"

    sync_fleet_update_script(str(src), str(dest))

    assert dest.stat().st_mode & stat.S_IXUSR


def test_leaves_an_identical_script_alone(src, tmp_path):
    """Avoid rewriting the updater on every boot."""
    dest = tmp_path / "update.sh"
    dest.write_text(src.read_text())
    before = dest.stat().st_mtime_ns

    assert sync_fleet_update_script(str(src), str(dest)) == "unchanged"
    assert dest.stat().st_mtime_ns == before


def test_missing_source_leaves_the_existing_updater_intact(tmp_path):
    """Degraded operation, not destruction: keep whatever the device already had."""
    dest = tmp_path / "update.sh"
    dest.write_text("#!/usr/bin/env bash\necho existing\n")

    assert sync_fleet_update_script(str(tmp_path / "absent.sh"), str(dest)) == "skipped"
    assert "existing" in dest.read_text()


def test_read_only_mount_does_not_raise(src, tmp_path):
    """A read-only /opt/fleet must not crash startup."""
    fleet = tmp_path / "ro"
    fleet.mkdir()
    dest = fleet / "update.sh"
    dest.write_text("#!/usr/bin/env bash\necho old\n")
    os.chmod(fleet, 0o500)

    try:
        assert sync_fleet_update_script(str(src), str(dest)) == "skipped"
        assert "old" in dest.read_text(), "the working updater must survive"
    finally:
        os.chmod(fleet, 0o700)


def test_no_temporary_files_are_left_behind(src, tmp_path):
    dest = tmp_path / "update.sh"

    sync_fleet_update_script(str(src), str(dest))

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".update.sh.")]
    assert not leftovers, f"temp file left behind: {leftovers}"


def test_a_failed_write_never_leaves_a_partial_script(src, tmp_path, monkeypatch):
    """If the move fails, the device must keep a whole, working updater.

    A truncated update.sh cannot be repaired remotely — it is the tool that would do
    the repairing.
    """
    dest = tmp_path / "update.sh"
    dest.write_text("#!/usr/bin/env bash\necho intact\n")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)

    assert sync_fleet_update_script(str(src), str(dest)) == "skipped"
    assert dest.read_text() == "#!/usr/bin/env bash\necho intact\n"
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".update.sh.")]
    assert not leftovers, f"temp file left behind: {leftovers}"
