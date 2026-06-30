#!/usr/bin/env python3
"""
Backfill git tags + GitHub Releases for the historical help.html versions.

Dry-run by default; pass --apply to actually create tags/Releases. Reuses the
unit-tested aq_lib.version_history for version extraction + first-appearance
reduction; this script only does the git/gh I/O.

Prereqs: run from the repo root with full git history and `gh` authenticated
with repo write access. Must be run AND pushed BEFORE the first cut-version
run, or the auto patch-bump has no latest tag to read.

    python3 scripts/backfill_version_tags.py            # dry-run (prints the plan)
    python3 scripts/backfill_version_tags.py --apply    # create tags + Releases
"""
import os
import subprocess
import sys

# Make the repo root importable when this script is run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aq_lib.version_history import extract_version, first_appearances

HELP = "aquila_web/static/help.html"


def collect():
    """Return [(sha, date, version)] for commits that set a footer version, oldest->newest."""
    log = subprocess.run(
        ["git", "log", "--reverse", "--format=%H %cI", "--", HELP],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    rows = []
    for line in log:
        if not line.strip():
            continue
        sha, date = line.split(" ", 1)
        blob = subprocess.run(["git", "show", f"{sha}:{HELP}"], capture_output=True, text=True)
        if blob.returncode != 0:
            continue
        version = extract_version(blob.stdout)
        if version:
            rows.append((sha, date, version))
    return rows


def plan(rows):
    """Reduce to the first commit at which each distinct version appears."""
    by_sha = {sha: (sha, date, version) for sha, date, version in rows}
    pairs = [(sha, version) for sha, _date, version in rows]
    return [by_sha[sha] for sha, _version in first_appearances(pairs)]


def main(argv):
    apply = "--apply" in argv
    selected = plan(collect())
    if not selected:
        print("No historical versions found.")
        return 0

    print("Planned version tags/Releases (oldest -> newest):")
    for sha, date, version in selected:
        print(f"  v{version}  <-  {sha[:8]}  ({date})")

    if not apply:
        print("\n[dry-run] nothing created. Re-run with --apply, then: git push origin --tags")
        return 0

    for sha, date, version in selected:
        tag = f"v{version}"
        if subprocess.run(["git", "rev-parse", tag], capture_output=True).returncode == 0:
            print(f"skip (exists): {tag}")
            continue
        subprocess.run(
            ["git", "tag", "-a", tag, sha, "-m",
             f"Backfilled release {version} — help.html @ {sha[:8]} (originally {date})"],
            env={**os.environ, "GIT_COMMITTER_DATE": date}, check=True,
        )
        subprocess.run(["git", "push", "origin", tag], check=True)
        subprocess.run(
            ["gh", "release", "create", tag, "--verify-tag",
             "--title", f"{tag} — {date.split('T')[0]} (backfilled)",
             "--notes", f"Originally released {date} (help.html @ {sha[:8]}). Backfilled.",
             "--latest=false"],
            check=True,
        )
        print(f"created: {tag}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
