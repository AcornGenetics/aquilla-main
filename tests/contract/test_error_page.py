"""Contract test: the general error page is the single operator-facing failure screen.

Issue #421. Every fatal failure — instrument fault, unhandled server exception,
failed navigation — resolves to this one page rather than raw state text or
unstyled framework output. It must render standalone: the operator may reach it
when the rest of the app is unhealthy, so it cannot depend on fetching anything.
"""
import pytest


def test_error_page_is_served(client):
    resp = client.get("/error")
    assert resp.status_code == 200


def test_error_page_shows_the_operator_wording(client):
    body = client.get("/error").text
    assert "Something went wrong" in body
    assert "Please try again or restart the device" in body
    assert "If the issue continues, contact Acorn Genetics for support." in body


def test_error_page_does_not_fetch_on_load(client):
    """It is reached when the app is unhealthy, so it must not depend on the API."""
    body = client.get("/error").text
    assert "fetch(" not in body
    assert "XMLHttpRequest" not in body


@pytest.fixture
def failing_route():
    """Register a route that blows up, so the unhandled-exception path is reachable."""
    from fastapi.testclient import TestClient

    from aquila_web import main as web_main

    @web_main.app.get("/__boom__")
    async def _boom():
        raise RuntimeError("kaboom")

    with TestClient(web_main.app, raise_server_exceptions=False) as c:
        yield c

    web_main.app.router.routes = [
        r for r in web_main.app.router.routes if getattr(r, "path", None) != "/__boom__"
    ]


def test_unhandled_exception_renders_the_error_page(failing_route):
    """An operator must never see a plain-text 'Internal Server Error'."""
    resp = failing_route.get("/__boom__")
    assert resp.status_code == 500
    assert "Something went wrong" in resp.text
    assert "contact Acorn Genetics for support." in resp.text
    assert "Internal Server Error" not in resp.text


def test_failed_navigation_renders_the_error_page(client):
    """A page request that fails must not paint a raw JSON body on the kiosk."""
    resp = client.get("/does-not-exist", headers={"Accept": "text/html"})
    assert "Something went wrong" in resp.text
    assert '"detail"' not in resp.text


def test_failed_api_call_still_returns_json(client):
    """Only navigations get HTML — the frontend's own fetches still need JSON."""
    resp = client.get("/does-not-exist", headers={"Accept": "application/json"})
    assert "Something went wrong" not in resp.text
