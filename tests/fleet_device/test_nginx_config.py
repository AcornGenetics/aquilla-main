"""
Static analysis of docker/nginx.conf to catch patterns that cause nginx to
crash on startup inside Docker containers.

These tests run without Docker — they parse the config file as text and verify
structural rules. A failure here means the next image build would produce a
container that crash-loops on every device.

Run with:
    pytest tests/fleet_device/test_nginx_config.py -v
"""
import re
from pathlib import Path

NGINX_CONF = Path("docker/nginx.conf")


def _read_conf() -> str:
    assert NGINX_CONF.exists(), f"{NGINX_CONF} not found"
    return NGINX_CONF.read_text()


def _location_blocks(conf: str) -> list[str]:
    """Extract each location { ... } block as a string."""
    blocks = []
    depth = 0
    current: list[str] = []
    inside = False
    for line in conf.splitlines():
        if re.match(r"\s*location\s+", line):
            inside = True
            depth = 0
            current = [line]
            continue
        if inside:
            current.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0 and "{" in "\n".join(current):
                blocks.append("\n".join(current))
                inside = False
                current = []
    return blocks


def test_nginx_conf_exists():
    """nginx.conf must exist in the docker/ directory."""
    assert NGINX_CONF.exists()


def test_host_docker_internal_has_resolver():
    """
    Any location block that proxy_passes to host.docker.internal must also
    declare a resolver directive. Without one, nginx resolves the upstream at
    startup and crashes if DNS isn't available yet — the bug that took down
    aquila-ui on SN01.
    """
    conf = _read_conf()
    for block in _location_blocks(conf):
        if "host.docker.internal" in block and "proxy_pass" in block:
            assert "resolver" in block, (
                "location block proxies to host.docker.internal but has no "
                "'resolver' directive — nginx will crash at startup on Linux.\n"
                f"Block:\n{block}"
            )


def test_no_bare_host_docker_internal_in_proxy_pass():
    """
    proxy_pass with host.docker.internal must use a variable ($upstream),
    not a literal URL. Literal URLs bypass the resolver and are looked up at
    startup, which fails when the host isn't yet resolvable.
    """
    conf = _read_conf()
    for block in _location_blocks(conf):
        if "host.docker.internal" not in block:
            continue
        # Find proxy_pass lines in this block
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("proxy_pass") and "host.docker.internal" in line:
                assert False, (
                    f"proxy_pass uses a literal host.docker.internal URL: '{line}'\n"
                    "Use a $variable with a resolver directive instead so nginx "
                    "defers DNS resolution to runtime."
                )


def test_backend_upstream_uses_container_name():
    """
    The backend upstream must be the Docker service name (aquila-backend), not
    localhost or a host IP. Container-to-container traffic goes via the Docker
    network.

    The name now appears in a `set $aq_backend http://aquila-backend:8090`
    directive rather than inline in proxy_pass, so nginx resolves it per request
    instead of at startup (#431). The container-name requirement is unchanged —
    only where the name is written has moved.
    """
    conf = _read_conf()
    assert "http://aquila-backend:8090" in conf, (
        "Backend upstream should use the container name 'aquila-backend', "
        "not localhost or a hardcoded IP."
    )
    assert "proxy_pass http://localhost" not in conf
    assert "proxy_pass http://127.0.0.1" not in conf


def test_backend_upstream_resolved_per_request():
    """
    Every proxy_pass to aquila-backend must go through a variable, so the name is
    resolved at request time. A literal upstream is resolved once at startup and
    nginx refuses to start if the backend container does not exist yet — which is
    exactly the state during boot, and the whole point of the splash fallback.

    Same failure mode that took down aquila-ui on sn01, previously only guarded
    for host.docker.internal.
    """
    conf = _read_conf()
    for line in conf.splitlines():
        line = line.strip()
        if line.startswith("proxy_pass") and "aquila-backend" in line:
            assert "$" in line, (
                "proxy_pass to aquila-backend must use a variable so the name is "
                f"resolved per request, not at startup:\n  {line}"
            )


def test_root_falls_back_to_splash_when_backend_is_down():
    """
    The kiosk opens / and never navigates away (#431). While the backend is
    starting nginx cannot connect, and that must serve the boot splash rather
    than an error page — otherwise the device shows a connection failure for the
    several seconds the app takes to come up.
    """
    conf = _read_conf()
    assert "error_page" in conf and "@splash" in conf, (
        "location = / must fall back to @splash on upstream failure"
    )
    assert "location @splash" in conf
    assert "/splash.html" in conf


def test_no_hardcoded_host_ips():
    """
    nginx.conf must not contain hardcoded host IPs like 172.x.x.x.
    These change between devices and environments.
    """
    conf = _read_conf()
    # Match IPv4 addresses in the 172.16-31 (Docker default bridge) range
    matches = re.findall(r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+", conf)
    assert not matches, (
        f"nginx.conf contains hardcoded Docker bridge IPs: {matches}. "
        "Use container service names or host.docker.internal with a resolver."
    )


def test_static_prefix_maps_to_flat_document_root():
    """
    The app references its assets relatively (href="static/styles.css"), which
    resolves to /static/… — but Dockerfile.ui copies aquila_web/static/ INTO the
    document root, so the files are at the top level with no static/ subdir.

    Serving that prefix with a plain root+try_files looks for
    /usr/share/nginx/html/static/styles.css, which does not exist: measured on
    sn10, /static/styles.css returned 404 and the app rendered unstyled.

    try_files must NOT be combined with alias here — it resolves $uri against the
    aliased path and reintroduces the same wrong directory.
    """
    conf = _read_conf()
    blocks = [b for b in _location_blocks(conf) if b.lstrip().startswith("location /static/")]
    assert blocks, "no location /static/ block found"
    block = blocks[0]
    assert "alias /usr/share/nginx/html/" in block, (
        "/static/ must alias the flat document root, not use root+try_files"
    )
    assert "try_files" not in block, (
        "try_files with alias resolves against the aliased path and breaks it"
    )


def test_backend_failure_is_fast():
    """
    While the backend container does not exist its name does not resolve. With
    nginx's defaults (30s resolver, 60s proxy) every splash health poll hung for
    a full minute — measured on sn10: 504 in 60.03s — so the splash stayed up
    long after the app was ready.

    The splash polls once a second and must not be blocked for longer than that
    by a backend which is simply not up yet.
    """
    conf = _read_conf()
    assert "resolver_timeout" in conf, (
        "resolver_timeout must be set — the 30s default stalls every poll while "
        "the backend container is absent"
    )
    assert "proxy_connect_timeout" in conf
