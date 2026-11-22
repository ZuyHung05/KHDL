"""Build and persist dataset collection manifests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checksum import sha256_file


def build_manifest(dataset_path: str | Path, commit_sha: str, source_url: str) -> dict[str, Any]:
    path = Path(dataset_path)
    return {
        "dataset": path.name,
        "commit_sha": commit_sha,
        "source_url": source_url,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "file": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_manifest(manifest: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
