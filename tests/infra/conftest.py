"""
Shared fixtures and path setup for Lambda handler unit tests.
Handlers are tested in-process — boto3, psycopg, and RPi libs are stubbed.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Make Lambda handler modules importable (mirrors Lambda runtime behaviour)
_HANDLERS_DIR = str(Path(__file__).parents[2] / "infra" / "handlers")
if _HANDLERS_DIR not in sys.path:
    sys.path.insert(0, _HANDLERS_DIR)

# Stub AWS SDK and PostgreSQL driver — not installed in the dev/CI environment
sys.modules.setdefault("boto3", MagicMock())
sys.modules.setdefault("psycopg", MagicMock())
