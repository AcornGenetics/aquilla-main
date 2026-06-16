import json
import os
from pathlib import Path

DEFAULT_SRC_BASEDIR = "/opt/aquila"
CONFIG_PATH = Path(__file__).with_name("config.json")


def get_src_basedir() -> str:
    env_value = os.getenv("AQ_SRC_BASEDIR")
    if env_value:
        return env_value
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
        except Exception:
            data = {}
        value = data.get("src_basedir") if isinstance(data, dict) else None
        if value and Path(value).exists():
            return value
    this_dir = str(Path(__file__).resolve().parent)
    if Path(this_dir).exists():
        return this_dir
    return DEFAULT_SRC_BASEDIR


def get_src_basedir_path() -> Path:
    return Path(get_src_basedir()).expanduser()
