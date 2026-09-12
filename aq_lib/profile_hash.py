"""Run-provenance fingerprint for a Profile.

``canonical_profile_hash`` produces a stable content fingerprint of a whole
Profile document, stamped into the ``run_complete`` event so a Run's exact
recipe is reconstructable even after the Profile is later changed
(issue #456 / acorn-fleet ADR-0002).

Canonicalization (sorted keys, compact separators) makes the fingerprint
immune to formatting/key-order noise while still changing on any real content
change. The ``canon-v1:`` tag records which canonicalization scheme produced the
digest, so a future revision stays distinguishable from old records.
"""
import hashlib
import json

_SCHEME = "canon-v1"


def canonical_profile_hash(profile: dict) -> str:
    """Return ``canon-v1:sha256:<hex>`` for a Profile document."""
    canonical = json.dumps(
        profile, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{_SCHEME}:sha256:{digest}"
