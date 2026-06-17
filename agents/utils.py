import json
import hashlib
from functools import lru_cache
from pathlib import Path
from datetime import datetime

import yaml

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
CONFIG_DIR = BASE_DIR / "config"

OUTPUT_DIR.mkdir(exist_ok=True)


@lru_cache(maxsize=1)
def load_policy_pack() -> dict:
    """Return the parsed policy_pack.yaml, cached after the first call."""
    path = CONFIG_DIR / "policy_pack.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def read_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_id(prefix: str, number: int) -> str:
    return f"{prefix}-{number:03d}"


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def timestamp() -> str:
    return datetime.utcnow().isoformat() + "Z"
