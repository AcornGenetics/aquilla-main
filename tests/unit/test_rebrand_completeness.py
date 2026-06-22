"""
Completeness guard for the aquila -> sentri rebrand (issue #186, ADR-016).

Asserts the retired `aquila` codename is absent from the source/config surfaces
this issue owns. The guard is intentionally NOT repo-wide: it excludes
- the deployment-pipeline files renamed in #187 (docker/, fleet-config/, etc.),
- the operational carve-outs that deliberately keep the codename
  (`AQ_` env-var prefix, `/opt/aquila` host path — see ADR-016),
- prose that documents the codename on purpose (CONTEXT.md, ADRs, this PRD).

Tokens are added one per TDD cycle as each namespace is renamed.
"""
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

# Exact package/module tokens, fully renamed (cycles 1-3).
FORBIDDEN_TOKENS = [
    "aq_curve",  # cycle 1
    "aq_lib",  # cycle 2
    "aquila_web",  # cycle 3
]

# Cycle 4: the brand WORD only. Matches `aquila`/`aquilla` (any case) as a
# standalone word, but NOT when it is part of a dashed/underscored deployment
# identifier (`aquila-backend`, `aquila_app`) or a path segment (`/opt/aquila`).
# Those are renamed in #187 (deployment) or are kept carve-outs (ADR-016).
BRAND_WORD = re.compile(r"(?<![\w/-])aquill?a(?![\w-])", re.IGNORECASE)

# Paths whose codename references are owned elsewhere or deliberately kept.
EXCLUDED_PATH_PREFIXES = (
    # --- deployment pipeline: renamed in #187 ---
    "docker/",
    "fleet-config/",
    "scripts/deploy/",
    "scripts/setup/",
    "compose.yaml",
    ".github/",
    # --- codename-documenting prose (intentional) ---
    "CONTEXT.md",
    "docs/adr/",
    "specs/prd/aquila-to-sentri-rebrand-prd.md",
    # --- rebrand guard tests: they name the codename to forbid it (#186/#187) ---
    "tests/unit/test_rebrand_completeness.py",
    "tests/fleet_device/test_compose_dns_integrity.py",
    "tests/fleet_device/test_image_path_agreement.py",
    "tests/fleet_device/test_service_unit_integrity.py",
    "tests/fleet_device/test_state_dir_param.py",
    "tests/fleet_device/test_selective_rename_guard.py",
    # --- agent/tooling session artifacts: recorded data, not product ---
    ".hive-mind/",
    ".claude/",
    ".claude-flow/",
    "logs/",
)

EXCLUDED_SUFFIXES = (".service",)  # systemd units -> #187

# Binary / non-text files we never scan.
BINARY_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".db", ".pyc",
    ".woff", ".woff2", ".ttf", ".so", ".bin", ".npy", ".gz", ".zip",
)


def _tracked_text_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    for rel in out:
        if rel.startswith(EXCLUDED_PATH_PREFIXES) or rel.endswith(EXCLUDED_SUFFIXES):
            continue
        if rel.endswith(BINARY_SUFFIXES):
            continue
        yield rel


@pytest.mark.parametrize("token", FORBIDDEN_TOKENS)
def test_codename_token_absent(token):
    offenders = []
    for rel in _tracked_text_files():
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if token in text:
            offenders.append(rel)
    assert not offenders, (
        f"{len(offenders)} file(s) still contain the retired token '{token}':\n"
        + "\n".join(f"  - {o}" for o in sorted(offenders))
    )


def test_brand_word_absent():
    offenders = []
    for rel in _tracked_text_files():
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if BRAND_WORD.search(text):
            offenders.append(rel)
    assert not offenders, (
        f"{len(offenders)} file(s) still use the brand word 'Aquila':\n"
        + "\n".join(f"  - {o}" for o in sorted(offenders))
    )
