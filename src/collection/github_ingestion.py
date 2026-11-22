"""Collect versioned files from independent GitHub sources."""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .checksum import sha256_file
from .manifest import build_manifest, write_manifest

LOGGER = logging.getLogger("it4930.collection")
DEFAULT_LOG = Path("logs/collection.jsonl")


def github_raw_url(url: str) -> str:
    """Convert GitHub blob links to raw URLs; leave raw URLs unchanged."""
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.netloc == "github.com" and len(parts) >= 5 and parts[2] == "blob":
        return f"https://raw.githubusercontent.com/{parts[0]}/{parts[1]}/{'/'.join(parts[3:])}"
    return url


def _safe_component(value: str, label: str) -> str:
    if not value or value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def _log_event(log_path: str | Path, event: dict) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def _download(url: str, target: Path) -> None:
    request = Request(url, headers={"User-Agent": "IT4930-data-collector/1.0"})
    with urlopen(request, timeout=60) as response, target.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if target.stat().st_size == 0:
        raise ValueError("Downloaded file is empty")


def _known_checksum(source_root: Path) -> str | None:
    """Return the checksum from the newest valid snapshot manifest, if any."""
    manifests = sorted(source_root.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            data_path = manifest_path.parent / manifest["file"]
            if data_path.is_file() and manifest.get("sha256"):
                actual = sha256_file(data_path)
                if actual == manifest["sha256"]:
                    return actual
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def collect(source: dict, output_root: str | Path = "data/raw", log_path: str | Path = DEFAULT_LOG) -> dict:
    """Collect one source config with unchanged detection and a versioned snapshot.

    Required source keys: source_id, url, filename, revision. Revision should be
    an immutable commit SHA or other stable source version identifier.
    """
    source_id = _safe_component(str(source["source_id"]), "source_id")
    revision = _safe_component(str(source["revision"]), "revision")
    filename = Path(str(source["filename"])).name
    if filename in {"", ".", ".."}:
        raise ValueError("filename must be a plain filename")
    source_url = github_raw_url(str(source["url"]))
    root = Path(output_root) / source_id
    temp = root / f".{filename}.part"
    started = datetime.now(timezone.utc).isoformat()
    try:
        root.mkdir(parents=True, exist_ok=True)
        _download(source_url, temp)
        checksum = sha256_file(temp)
        previous = _known_checksum(root)
        if previous == checksum:
            temp.unlink(missing_ok=True)
            event = {"status": "SKIPPED_UNCHANGED", "source_id": source_id, "revision": revision,
                     "filename": filename, "source_url": source_url, "sha256": checksum,
                     "collected_at": started}
            _log_event(log_path, event)
            LOGGER.info("Skipped unchanged source %s", source_id)
            return event

        destination = root / revision
        destination.mkdir(parents=True, exist_ok=True)
        data_path = destination / filename
        temp.replace(data_path)
        manifest = build_manifest(data_path, revision, source_url)
        manifest.update({"source_id": source_id, "revision": revision, "status": "COLLECTED"})
        write_manifest(manifest, destination / "manifest.json")
        event = {**manifest, "status": "COLLECTED", "path": str(data_path)}
        _log_event(log_path, event)
        LOGGER.info("Collected %s at %s", source_id, data_path)
        return event
    except Exception as exc:
        temp.unlink(missing_ok=True)
        event = {"status": "FAILED", "source_id": source_id, "revision": revision,
                 "filename": filename, "source_url": source_url,
                 "error": f"{type(exc).__name__}: {exc}", "collected_at": started}
        _log_event(log_path, event)
        LOGGER.exception("Collection failed for %s", source_id)
        return event


def collect_many(sources: list[dict], output_root: str | Path = "data/raw",
                 log_path: str | Path = DEFAULT_LOG) -> list[dict]:
    """Process independent sources; a failure does not stop later sources."""
    results = []
    for source in sources:
        try:
            results.append(collect(source, output_root, log_path))
        except Exception as exc:
            # Invalid config may fail before collect can build its usual event.
            event = {"status": "FAILED", "source_id": source.get("source_id"),
                     "error": f"{type(exc).__name__}: {exc}",
                     "collected_at": datetime.now(timezone.utc).isoformat()}
            _log_event(log_path, event)
            LOGGER.exception("Invalid source configuration")
            results.append(event)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="JSON file containing a list of source objects")
    parser.add_argument("--output-root", default="data/raw")
    parser.add_argument("--log-path", default="logs/collection.jsonl")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    sources = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if isinstance(sources, dict):
        sources = [sources]
    if not isinstance(sources, list):
        parser.error("config must contain a source object or a list of source objects")
    results = collect_many(sources, args.output_root, args.log_path)
    if any(result["status"] == "FAILED" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
