"""
Version-computation helper for the cut-version release workflow.

Pure logic: the workflow supplies the latest tag and the set of existing
versions; this module decides the next version. No git / network I/O here.
"""
import re

_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")

ALLOWED_RINGS = ("dev", "pilot", "prod")


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


def validate_ring_assignment(version, ring, existing_versions):
    """Raise ValueError unless ``version`` (a built image) may be assigned to
    ``ring``. A no-op return means the assignment is allowed."""
    if ring not in ALLOWED_RINGS:
        raise ValueError(f"invalid ring {ring!r} (allowed: {', '.join(ALLOWED_RINGS)})")
    if version not in existing_versions:
        raise ValueError(f"version {version} has no built image — cut it first")
    return None


def _main(argv=None):
    """Thin CLI for the workflow. The caller supplies the latest tag and the
    existing versions read from git/registry — this module does no I/O itself.

    Subcommands:
      next   --latest --custom --existing   -> prints the next version
      assign --version --ring --existing    -> validates a ring assignment
    Both exit non-zero with an error on stderr on rejection.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Release version helper.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_next = sub.add_parser("next", help="compute the next version")
    p_next.add_argument("--latest", required=True, help="latest existing version, e.g. 1.2.6.6")
    p_next.add_argument("--custom", default="", help="exact version (blank = auto patch-bump)")
    p_next.add_argument("--existing", default="", help="comma-separated existing versions")

    p_assign = sub.add_parser("assign", help="validate assigning a version to a ring")
    p_assign.add_argument("--version", required=True, help="version to assign")
    p_assign.add_argument("--ring", required=True, help="dev/pilot/prod")
    p_assign.add_argument("--existing", default="", help="comma-separated built versions")

    args = parser.parse_args(argv)
    existing = {v for v in args.existing.split(",") if v}

    if args.cmd == "next":
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

    if args.cmd == "assign":
        try:
            validate_ring_assignment(args.version, args.ring, existing)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{args.version} -> {args.ring}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
