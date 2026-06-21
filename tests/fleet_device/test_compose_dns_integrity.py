"""
D1 — Compose service-DNS integrity (rebrand #187, ADR-015).

The fleet runs as Docker Compose services that reach each other by
container_name over the compose network (e.g. the UI's nginx proxies to
`http://aquila-backend:8090`). If a container_name is renamed but a reference
to it is missed, the containers build fine but the UI cannot reach the backend
at runtime — a silent, device-only outage.

These tests parse the compose files + nginx.conf + entrypoint.sh as text (no
Docker needed) and assert:
  - every `http://NAME:PORT` reference resolves to a declared container/service
    (the permanent integrity invariant), and
  - the brand rename actually happened — no `aquila-*` container names remain.
"""
import re
from pathlib import Path

COMPOSE_FILES = [
    Path("fleet-config/docker-compose.yml"),
    Path("docker/docker-compose.yml"),
]
# Files that reference containers by DNS name but declare none themselves.
DNS_REF_FILES = [
    Path("docker/nginx.conf"),
    Path("docker/entrypoint.sh"),
]

CONTAINER_NAME_RE = re.compile(r"container_name:\s*([A-Za-z0-9_-]+)")
SERVICE_HEADER_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.MULTILINE)
DNS_REF_RE = re.compile(r"http://([A-Za-z0-9_-]+):\d+")


def _declared_names() -> set[str]:
    names: set[str] = set()
    for f in COMPOSE_FILES:
        if not f.exists():
            continue
        text = f.read_text()
        names.update(CONTAINER_NAME_RE.findall(text))
        names.update(SERVICE_HEADER_RE.findall(text))
    return names


def _dns_references() -> dict[str, list[str]]:
    """name -> files referencing it via http://name:port"""
    refs: dict[str, list[str]] = {}
    for f in COMPOSE_FILES + DNS_REF_FILES:
        if not f.exists():
            continue
        for name in DNS_REF_RE.findall(f.read_text()):
            refs.setdefault(name, []).append(str(f))
    return refs


def test_dns_refs_resolve_to_declared_containers():
    declared = _declared_names()
    refs = _dns_references()
    unresolved = {n: files for n, files in refs.items() if n not in declared}
    assert not unresolved, (
        "service-DNS reference(s) not matching any declared container_name/service:\n"
        + "\n".join(f"  - {n} (in {', '.join(files)})" for n, files in sorted(unresolved.items()))
    )


def test_container_names_use_sentri_brand():
    declared = _declared_names()
    stale = sorted(n for n in declared if n.startswith("aquila-"))
    assert not stale, f"container/service still on the old codename: {stale}"
