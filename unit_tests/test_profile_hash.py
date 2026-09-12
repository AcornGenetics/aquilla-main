"""
Unit tests for aq_lib/profile_hash.py — canonical_profile_hash(profile) -> str.

Pure logic, no hardware or network. Produces the run-provenance fingerprint
stamped into the ``run_complete`` event so a Run's exact recipe is reconstructable
even after the Profile is later changed (issue #456 / acorn-fleet ADR-0002).
Marked ``unit``.
"""
import re

import pytest

from aq_lib.profile_hash import canonical_profile_hash

pytestmark = pytest.mark.unit


def _profile():
    return {
        "title": "Beer Spoilers - Bacteria",
        "steps": [{"setpoint": 94, "duration": 240}],
        "labels": {"fam": "FAM", "rox": "ROX"},
    }


def test_hash_is_canon_v1_sha256_tagged():
    """The fingerprint is a canon-v1-tagged SHA-256 hex digest."""
    digest = canonical_profile_hash(_profile())
    assert re.fullmatch(r"canon-v1:sha256:[0-9a-f]{64}", digest)


def test_hash_is_invariant_to_key_order():
    """Reordering keys (e.g. an editor re-serialising) does not change the hash."""
    a = {"title": "X", "steps": [{"setpoint": 94, "duration": 240}]}
    b = {"steps": [{"duration": 240, "setpoint": 94}], "title": "X"}
    assert canonical_profile_hash(a) == canonical_profile_hash(b)


def test_hash_changes_when_any_field_changes():
    """Any real content change — including outside ``steps`` — flips the hash."""
    base = _profile()
    changed_setpoint = {**base, "steps": [{"setpoint": 95, "duration": 240}]}
    changed_label = {**base, "labels": {"fam": "FAM", "rox": "HEX"}}
    assert canonical_profile_hash(base) != canonical_profile_hash(changed_setpoint)
    assert canonical_profile_hash(base) != canonical_profile_hash(changed_label)
