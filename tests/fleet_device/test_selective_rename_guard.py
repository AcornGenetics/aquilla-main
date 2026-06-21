"""
D4 — selective-rename guard for the deployment pipeline (rebrand #187, ADR-015).

The rebrand is deliberately selective: brand/deployment identifiers
(`aquila-*` containers, `aquilla-main` image paths, `aquila_*` units) are
renamed to `sentri`, but two operational seams are KEPT as carve-outs because
they are stateful contracts with the live fleet:
  - the `AQ_` environment-variable prefix (cert-bound device identity, etc.)
  - the `/opt/aquila` host state directory

This guard asserts both sides at once across the deployment files: no codename
identifier survives, and the carve-outs are still present.
"""
import re
from pathlib import Path

DEPLOY_FILES = [
    Path("fleet-config/docker-compose.yml"),
    Path("docker/docker-compose.yml"),
    Path("docker/entrypoint.sh"),
    Path("docker/nginx.conf"),
    Path("scripts/deploy/fleet-update.sh"),
    Path("scripts/deploy/deployment2.sh"),
]

# brand/deployment identifiers that must be gone (NOT matching /opt/aquila or AQ_)
IDENTIFIER_RE = re.compile(r"aquilla|aquila[-_]")


def test_no_codename_identifiers_in_deploy_files():
    offenders = {}
    for f in DEPLOY_FILES:
        if not f.exists():
            continue
        hits = sorted(set(IDENTIFIER_RE.findall(f.read_text())))
        # /opt/aquila is a kept path, not an identifier — it never matches the regex above.
        bad = [h for h in hits]
        if bad:
            offenders[str(f)] = bad
    assert not offenders, "codename identifier(s) left in deploy files:\n" + "\n".join(
        f"  - {f}: {h}" for f, h in sorted(offenders.items())
    )


def test_opt_aquila_carveout_preserved():
    # /opt/aquila is the host state dir — must survive the rebrand.
    keepers = [str(f) for f in DEPLOY_FILES if f.exists() and "/opt/aquila" in f.read_text()]
    assert keepers, "expected /opt/aquila to remain in the deployment files (carve-out)"


def test_aq_env_prefix_carveout_preserved():
    # AQ_ env vars (e.g. AQ_SYNC_DEVICE_ID) must NOT be renamed to SENTRI_.
    text = " ".join(f.read_text() for f in DEPLOY_FILES if f.exists())
    assert re.search(r"\bAQ_[A-Z]", text), "expected AQ_ env vars to remain (carve-out)"
    assert "SENTRI_SYNC" not in text, "AQ_ env vars must not be renamed to SENTRI_"
