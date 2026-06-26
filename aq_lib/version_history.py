"""
History logic for the version backfill.

Pure functions: parse the footer version out of a help.html blob, and reduce
a version-per-commit history to first appearances. No git I/O here — the
backfill script supplies the commits/blobs.
"""
import re

_VERSION_SPAN_RE = re.compile(r'id="help-version-info"[^>]*>\s*V\s*([\d.]+)')


def extract_version(html):
    """Return the footer version (e.g. ``1.2.6.6``) in a help.html blob, or None."""
    match = _VERSION_SPAN_RE.search(html)
    return match.group(1) if match else None


def first_appearances(pairs):
    """Given ``(commit, version)`` pairs ordered oldest->newest, return the
    pair for the first commit at which each distinct version appears."""
    seen = set()
    result = []
    for commit, version in pairs:
        if version not in seen:
            seen.add(version)
            result.append((commit, version))
    return result
