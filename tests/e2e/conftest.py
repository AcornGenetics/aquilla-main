"""
Playwright fixtures for Layer 5 UI regression tests.
Requires: pip install playwright pytest-playwright
          playwright install chromium
"""
import pytest


@pytest.fixture(scope="session")
def base_url():
    """URL of the running frontend. Override with AQUILA_TEST_URL env var."""
    import os
    return os.environ.get("AQUILA_TEST_URL", "http://localhost:8090")


@pytest.fixture(scope="session")
def browser_context_args():
    """Touch-enabled viewport matching the kiosk display."""
    return {
        "viewport": {"width": 768, "height": 1024},
        "has_touch": True,
    }
