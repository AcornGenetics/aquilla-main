"""
Behavior tests for the fleet cutover orchestrator (#188, ADR-016).

`scripts/deploy/flip-fleet.sh` flips devices from the old image namespace to
`acorngenetics/sentri` over (Tailscale) SSH: per device it points
GHCR_REPO at the new repo and runs fleet-update.sh. The mid-run guard inside
fleet-update.sh means a device with a live PCR run is deferred, not interrupted.

Safety contract: the orchestrator is **dry-run by default** — it touches no
device unless `--execute` is passed. Tests drive it through its real interface
(stdout + exit code) with a fake SSH command so they never touch a real fleet.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FLIP = REPO_ROOT / "scripts" / "deploy" / "flip-fleet.sh"


@pytest.fixture
def fake_ssh(tmp_path):
    """A stub `ssh` that records each invocation; yields (ssh_path, calls_file).

    Per-device exit code can be steered by writing 'HOSTNAME=CODE' lines into
    an EXIT_MAP file the stub reads."""
    calls = tmp_path / "ssh_calls.log"
    exit_map = tmp_path / "exit_map"
    exit_map.write_text("")
    ssh = tmp_path / "fake_ssh"
    ssh.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> "{calls}"\n'
        'host="$1"\n'
        f'code=$(grep "^${{host}}=" "{exit_map}" 2>/dev/null | cut -d= -f2)\n'
        'exit "${code:-0}"\n'
    )
    ssh.chmod(0o755)
    yield ssh, calls, exit_map


def _devices_file(tmp_path, *hosts):
    f = tmp_path / "devices.txt"
    f.write_text("\n".join(hosts) + "\n")
    return f


def _run(devfile, fake_ssh_path, *args):
    return subprocess.run(
        ["bash", str(FLIP), "--devices", str(devfile), *args],
        env={"SSH_CMD": str(fake_ssh_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )


def test_dry_run_lists_devices_without_touching_them(tmp_path, fake_ssh):
    ssh, calls, _ = fake_ssh
    devfile = _devices_file(tmp_path, "sn01", "sn02")

    result = _run(devfile, ssh)  # no --execute

    assert result.returncode == 0
    assert "sn01" in result.stdout and "sn02" in result.stdout
    assert not calls.exists(), "dry-run must not invoke ssh"


def test_execute_flips_each_device_to_sentri(tmp_path, fake_ssh):
    ssh, calls, _ = fake_ssh
    devfile = _devices_file(tmp_path, "sn01", "sn02")

    result = _run(devfile, ssh, "--execute")

    assert result.returncode == 0
    log = calls.read_text()
    # one ssh invocation per device, each pointing GHCR_REPO at the new repo
    assert log.count("sn01") >= 1 and log.count("sn02") >= 1
    assert "acorngenetics/sentri" in log
    assert "fleet-update.sh" in log


def test_mid_run_device_is_deferred_not_interrupted(tmp_path, fake_ssh):
    ssh, calls, exit_map = fake_ssh
    exit_map.write_text("sn01=3\n")  # run_guard.sh exit 3 == run in progress
    devfile = _devices_file(tmp_path, "sn01", "sn02")

    result = _run(devfile, ssh, "--execute")

    # sn01 deferred; sn02 still attempted (deferral must not abort the run)
    assert "sn02" in calls.read_text()
    assert "deferred" in result.stdout.lower()
    assert "sn01" in result.stdout
    # a device still needing a follow-up flip -> non-zero so the operator knows
    assert result.returncode != 0


def test_failed_device_is_reported_distinctly(tmp_path, fake_ssh):
    ssh, _, exit_map = fake_ssh
    exit_map.write_text("sn02=1\n")  # generic failure, not the mid-run defer code
    devfile = _devices_file(tmp_path, "sn01", "sn02")

    result = _run(devfile, ssh, "--execute")

    assert "failed" in result.stdout.lower()
    assert result.returncode != 0


def test_missing_devices_file_errors_clearly(tmp_path, fake_ssh):
    ssh, _, _ = fake_ssh

    result = subprocess.run(
        ["bash", str(FLIP), "--devices", str(tmp_path / "nope.txt"), "--execute"],
        env={"SSH_CMD": str(ssh), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert "devices" in result.stderr.lower()
