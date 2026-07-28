"""A version mismatch announces itself rather than waiting to be found (#352).

Two checks, both on git SHAs and never on build timestamps:

  A. api.git_sha == ui.git_sha      — same build, no network needed
  B. running build == what the fleet config claims, bridged through the
     org.opencontainers.image.revision label from #351

`identity_ok` is deliberately three-valued. A check that could not run must
report null, never true — a check that silently passes when it could not run is
the exact failure the OTA status issue documents.
"""
import asyncio

import pytest

from aquila_web import main


@pytest.fixture(autouse=True)
def _reset_identity(monkeypatch):
    monkeypatch.setattr(main, "_identity_state", dict(main._identity_state))
    monkeypatch.setattr(main, "_BUILD_IDENTITY",
                        {"app_version": "2.1.0.5", "git_sha": "aaa111", "build_time": "t"})
    monkeypatch.setenv("RUNNING_IMAGE_DIGEST", "sha256:deadbeef")
    monkeypatch.setattr(main, "_OTA_GHCR_TOKEN", "token")
    yield


def _ui(monkeypatch, sha, err=None):
    async def fake():
        return sha, err
    monkeypatch.setattr(main, "_fetch_ui_identity", fake)


def _registry(monkeypatch, sha, err=None):
    async def fake(repo, digest, user, token):
        return sha, err
    monkeypatch.setattr(main, "_ghcr_revision_for_digest", fake)


# ── The three-valued rule ─────────────────────────────────────────────────────

@pytest.mark.parametrize("images,digest,expected", [
    (True,  True,  True),
    (True,  False, False),
    (False, True,  False),
    (False, False, False),
    (True,  None,  None),   # could not verify — NOT true
    (None,  True,  None),
    (None,  None,  None),
    (False, None,  False),  # a known failure beats an unknown
    (None,  False, False),
])
def test_identity_ok_resolution(images, digest, expected):
    assert main._resolve_identity_ok(images, digest) is expected


# ── Check A: do the two images come from the same build? ──────────────────────

def test_matching_images_and_digest_verify(monkeypatch):
    _ui(monkeypatch, "aaa111")
    _registry(monkeypatch, "aaa111")
    asyncio.run(main._check_build_identity())
    assert main._identity_state["images_match"] is True
    assert main._identity_state["digest_matches"] is True
    assert main._identity_state["identity_ok"] is True


def test_api_and_ui_from_different_builds_is_a_mismatch(monkeypatch):
    _ui(monkeypatch, "bbb222")
    _registry(monkeypatch, "aaa111")
    asyncio.run(main._check_build_identity())
    assert main._identity_state["images_match"] is False
    assert main._identity_state["identity_ok"] is False


def test_unreachable_ui_is_unknown_not_a_pass(monkeypatch):
    _ui(monkeypatch, None, "Could not reach the UI container")
    _registry(monkeypatch, "aaa111")
    asyncio.run(main._check_build_identity())
    assert main._identity_state["images_match"] is None
    assert main._identity_state["identity_ok"] is None
    assert main._identity_state["error"]


# ── Check B: is the running build the one the config claims? ──────────────────

def test_running_build_differing_from_the_recorded_digest_is_a_mismatch(monkeypatch):
    """RUNNING_IMAGE_DIGEST is written before the swap, so it can claim a build
    the device never actually started running."""
    _ui(monkeypatch, "aaa111")
    _registry(monkeypatch, "ccc333")  # the digest was built from a different commit
    asyncio.run(main._check_build_identity())
    assert main._identity_state["digest_matches"] is False
    assert main._identity_state["identity_ok"] is False


def test_unreachable_registry_is_unknown_not_a_pass(monkeypatch):
    _ui(monkeypatch, "aaa111")
    _registry(monkeypatch, None, main._ERR_NETWORK)
    asyncio.run(main._check_build_identity())
    assert main._identity_state["digest_matches"] is None
    assert main._identity_state["identity_ok"] is None


def test_no_recorded_digest_leaves_check_b_unknown(monkeypatch):
    monkeypatch.delenv("RUNNING_IMAGE_DIGEST", raising=False)
    _ui(monkeypatch, "aaa111")
    asyncio.run(main._check_build_identity())
    assert main._identity_state["images_match"] is True
    assert main._identity_state["digest_matches"] is None
    assert main._identity_state["identity_ok"] is None


def test_image_built_before_351_cannot_verify(monkeypatch):
    """No baked SHA — degrade to unknown rather than claiming a pass."""
    monkeypatch.setattr(main, "_BUILD_IDENTITY",
                        {"app_version": "2.1.0.5", "git_sha": "unknown", "build_time": "unknown"})
    _ui(monkeypatch, "aaa111")
    _registry(monkeypatch, "aaa111")
    asyncio.run(main._check_build_identity())
    assert main._identity_state["identity_ok"] is None


# ── Reporting ─────────────────────────────────────────────────────────────────

def test_identity_endpoint_reports_the_state(client, monkeypatch):
    _ui(monkeypatch, "bbb222")
    _registry(monkeypatch, "aaa111")
    asyncio.run(main._check_build_identity())
    body = client.get("/identity").json()
    assert body["identity_ok"] is False
    assert body["api_git_sha"] == "aaa111"
    assert body["ui_git_sha"] == "bbb222"
    assert body["checked_at"]


def test_mismatch_is_emitted_to_the_outbox(monkeypatch):
    """An on-screen warning only helps someone standing at the device."""
    sent = []
    monkeypatch.setattr(main, "enqueue_event",
                        lambda t, p, **kw: sent.append((t, p, kw)) or 1)
    _ui(monkeypatch, "bbb222")
    _registry(monkeypatch, "aaa111")
    asyncio.run(main._check_build_identity())
    assert sent and sent[0][0] == "identity_mismatch"
    assert sent[0][2].get("dedup_key"), "must dedup or every poll re-sends it"


def test_matching_identity_emits_nothing(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "enqueue_event", lambda t, p, **kw: sent.append(t) or 1)
    _ui(monkeypatch, "aaa111")
    _registry(monkeypatch, "aaa111")
    asyncio.run(main._check_build_identity())
    assert sent == []


def test_repeated_mismatch_emits_once(monkeypatch):
    """Only on transition — otherwise every poll floods the outbox."""
    sent = []
    monkeypatch.setattr(main, "enqueue_event", lambda t, p, **kw: sent.append(t) or 1)
    _ui(monkeypatch, "bbb222")
    _registry(monkeypatch, "aaa111")
    asyncio.run(main._check_build_identity())
    asyncio.run(main._check_build_identity())
    assert len(sent) == 1


def test_build_time_is_never_a_comparison_key():
    """Posit found timestamp-based tracking unreliable across build nodes, and
    these Pis have no RTC. build_time is informational only."""
    import inspect
    src = inspect.getsource(main._check_build_identity)
    assert "build_time" not in src, "identity comparison must key off git_sha only"


def test_manual_check_endpoint_reruns_the_check(client, monkeypatch):
    """Used by post-deploy verification and by the operator's "Try again"."""
    _ui(monkeypatch, "bbb222")
    _registry(monkeypatch, "aaa111")
    body = client.post("/identity/check").json()
    assert body["ok"] is True
    assert body["identity_ok"] is False
    assert body["ui_git_sha"] == "bbb222"
