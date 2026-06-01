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
    The main backend proxy_pass must use the Docker service name
    (aquila-backend), not localhost or a host IP. Container-to-container
    traffic must go via the Docker network.
    """
    conf = _read_conf()
    assert "proxy_pass http://aquila-backend:" in conf, (
        "Main backend proxy_pass should use the container name 'aquila-backend', "
        "not localhost or a hardcoded IP."
    )


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
