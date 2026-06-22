"""
Contract tests for the mid-run update guard's backend signal (#188, ADR-002).

The fleet updater (`scripts/deploy/fleet-update.sh`) must not recreate
containers while a PCR run is in progress — doing so kills the run. The
device exposes that state on GET /health so the host-side updater can poll it
and defer the device. ADR-002 flagged this as "not currently enforced".

GET /health -> {"status": "ok", "run_in_progress": bool}
"""


def test_health_reports_idle_when_no_run_in_progress(client):
    body = client.get("/health").json()

    assert body["status"] == "ok"  # existing contract preserved
    assert body["run_in_progress"] is False


def test_health_reports_run_in_progress_while_running(client, monkeypatch):
    from sentri_web import main as web_main
    monkeypatch.setattr(web_main, "run_in_progress", True)

    body = client.get("/health").json()

    assert body["run_in_progress"] is True
