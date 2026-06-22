"""
Behavior tests for the mid-run update guard (#188, ADR-002).

`scripts/deploy/run_guard.sh` is the safety check the fleet updater runs before
recreating containers. It polls the backend /health and decides whether it is
safe to update this device:

  exit 0  -> idle, safe to update
  exit !0 -> a run is in progress, OR run state can't be confirmed (fail-closed)

The guard is exercised through its real interface — the shell process and its
exit code — against a stub /health endpoint, so these tests survive any
refactor of the script internals.
"""
import http.server
import json
import subprocess
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "deploy" / "run_guard.sh"


@pytest.fixture
def health_stub():
    """Serve a controllable /health payload; yield (base_url, set_body)."""
    state = {"body": {"status": "ok", "run_in_progress": False}}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            payload = json.dumps(state["body"]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass  # keep test output clean

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    def set_body(body):
        state["body"] = body

    try:
        yield f"http://{host}:{port}/health", set_body
    finally:
        server.shutdown()
        server.server_close()


def _run_guard(health_url, *args):
    return subprocess.run(
        ["bash", str(GUARD), *args],
        env={"HEALTH_URL": health_url, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )


def test_guard_blocks_when_run_in_progress(health_stub):
    health_url, set_body = health_stub
    set_body({"status": "ok", "run_in_progress": True})

    result = _run_guard(health_url)

    assert result.returncode != 0
    # the guard refused *because of the run*, not because the script is missing
    assert "progress" in result.stderr.lower()


def test_guard_proceeds_when_idle(health_stub):
    health_url, set_body = health_stub
    set_body({"status": "ok", "run_in_progress": False})

    result = _run_guard(health_url)

    assert result.returncode == 0


def test_force_overrides_run_in_progress(health_stub):
    health_url, set_body = health_stub
    set_body({"status": "ok", "run_in_progress": True})

    result = _run_guard(health_url, "--force")

    assert result.returncode == 0


def test_unreachable_backend_blocks_fail_closed():
    # No server: an unconfirmable run state must refuse the update (fail-closed).
    result = _run_guard("http://127.0.0.1:9/health")  # port 9 (discard) — refused

    assert result.returncode != 0

    forced = _run_guard("http://127.0.0.1:9/health", "--force")
    assert forced.returncode == 0


def test_fleet_update_runs_guard_before_recreating_containers():
    """The guard is only useful if the updater aborts on its non-zero exit
    *before* the destructive `docker compose ... up -d`."""
    text = (REPO_ROOT / "scripts" / "deploy" / "fleet-update.sh").read_text()
    # only executable lines — a comment mentioning `up -d` isn't the command
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]

    guard_idx = next(i for i, ln in enumerate(lines) if "run_guard.sh" in ln)
    up_idx = next(i for i, ln in enumerate(lines) if "up -d" in ln)

    assert guard_idx < up_idx, "run_guard.sh must be invoked before `up -d`"
    # the updater must honor the guard's verdict (abort on non-zero), and pass
    # through operator flags like --force
    guard_line = lines[guard_idx]
    assert "exit" in guard_line or "||" in guard_line, (
        "fleet-update.sh must abort when run_guard.sh exits non-zero"
    )
    assert '"$@"' in guard_line, "fleet-update.sh must forward args (e.g. --force) to the guard"
