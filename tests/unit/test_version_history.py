"""
Unit tests for the backfill's history logic: pulling the footer version out
of a help.html blob, and reducing a version-per-commit history to the first
appearance of each distinct version. Pure logic — no git I/O.
"""
from aq_lib.version_history import extract_version, first_appearances


def test_extract_version_from_footer_span():
    html = '<span class="help-footer__meta" id="help-version-info">V 1.2.6.6</span>'
    assert extract_version(html) == "1.2.6.6"


def test_extract_version_tolerates_multiline_span():
    """The git history has the span split across lines with indentation."""
    html = (
        '<span class="help-footer__meta" id="help-version-info"\n'
        "              >V 1.2.5.5</span\n"
        "              >"
    )
    assert extract_version(html) == "1.2.5.5"


def test_extract_version_returns_none_when_absent():
    """An old commit with no version footer yields no version."""
    assert extract_version("<div>no footer here</div>") is None


def test_first_appearances_keeps_first_of_each_distinct_version():
    """Consecutive repeats collapse to the commit where the version first appeared."""
    pairs = [("a", "1.2.5"), ("b", "1.2.5"), ("c", "1.2.6")]
    assert first_appearances(pairs) == [("a", "1.2.5"), ("c", "1.2.6")]


def test_first_appearances_ignores_version_reappearing_after_revert():
    """If a version reappears later (e.g. a revert), only its first commit is kept."""
    pairs = [("a", "1.2.6.5"), ("b", "1.2.6.6"), ("c", "1.2.6.5")]
    assert first_appearances(pairs) == [("a", "1.2.6.5"), ("b", "1.2.6.6")]
