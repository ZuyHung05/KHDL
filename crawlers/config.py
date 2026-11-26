from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]

LOGGER = logging.getLogger("it4930.crawlers.config")


def load_crawler_config(path: str | Path = ROOT / "configs/crawlers.yaml") -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream or {}) or {}


def browser_config(section: str = "browser") -> dict[str, Any]:
    return load_crawler_config().get(section, {})
