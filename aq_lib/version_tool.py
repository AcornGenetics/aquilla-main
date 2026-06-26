"""
Version-computation helper for the cut-version release workflow.

Pure logic: the workflow supplies the latest tag and the set of existing
versions; this module decides the next version. No git / network I/O here.
"""
import re

_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


def is_valid_version(s):
    """True if ``s`` is dot-separated integers (e.g. ``1.2.6.7``)."""
    return bool(_VERSION_RE.match(s))


def _version_key(s):
    """Numeric sort key for a dotted version string."""
    return tuple(int(p) for p in s.split("."))


def sorts_below(candidate, latest):
    """True if ``candidate`` orders earlier than ``latest`` numerically
    (used to warn about a likely-mistyped custom version)."""
    return _version_key(candidate) < _version_key(latest)


def resolve_next(latest, custom, existing):
    """Return the next version to cut.

    A custom version (when given) is used verbatim; otherwise increment the
    last segment of ``latest``.
    """
    if custom:
        if not is_valid_version(custom):
            raise ValueError(f"invalid version format: {custom!r}")
        if custom in existing:
            raise ValueError(f"version {custom} already exists (versions are write-once)")
        return custom
    parts = latest.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def _main(argv=None):
    """Thin CLI for the workflow: prints the next version, or exits non-zero
    with an error on stderr. The caller (workflow) supplies the latest tag and
    the existing versions read from git — this module does no git I/O itself.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Compute the next release version.")
    parser.add_argument("--latest", required=True, help="latest existing version, e.g. 1.2.6.6")
    parser.add_argument("--custom", default="", help="exact version to cut (blank = auto patch-bump)")
    parser.add_argument("--existing", default="", help="comma-separated existing versions")
    args = parser.parse_args(argv)

    existing = {v for v in args.existing.split(",") if v}
    custom = args.custom or None
    try:
        version = resolve_next(args.latest, custom, existing)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if custom and sorts_below(custom, args.latest):
        print(f"warning: {custom} sorts below latest {args.latest}", file=sys.stderr)
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
