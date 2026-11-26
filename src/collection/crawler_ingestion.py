"""Run a job-board crawler and store its JSONL output as a checksummed snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .checksum import sha256_file
from .manifest import write_manifest

LOGGER = logging.getLogger("it4930.crawler_collection")
DEFAULT_LOG = Path("logs/collection.jsonl")


def _crawler_sites() -> dict[str, str]:
    import yaml

    from crawlers.config import ROOT

    data = yaml.safe_load((ROOT / "configs/crawlers.yaml").read_text(encoding="utf-8")) or {}
    return {
        sid: cfg["url"]
        for sid, cfg in (data.get("sites") or {}).items()
        if cfg.get("url") and cfg.get("enabled", True)
    }


CRAWLERS = _crawler_sites()


def _safe_component(value: str, label: str) -> str:
    if not value or not re.fullmatch(r"[A-Za-z0-9._-]+", value) or value in {".", ".."}:
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def _log(log_path: str | Path, event: dict) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def _run_subprocess(command: list[str]) -> subprocess.CompletedProcess:
    """Forward Ctrl+C to an isolated crawler, then let it clean up normally."""
    process = subprocess.Popen(command, start_new_session=True)
    previous_handler = signal.getsignal(signal.SIGINT)

    def forward_interrupt(_signum, _frame):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)

    signal.signal(signal.SIGINT, forward_interrupt)
    try:
        returncode = process.wait()
        return subprocess.CompletedProcess(command, returncode)
    finally:
        signal.signal(signal.SIGINT, previous_handler)


def _snapshot_revision(listings_path: Path, jobs_path: Path, errors_path: Path | None) -> tuple[str, dict]:
    checksums = {
        "listings.jsonl": sha256_file(listings_path),
        "jobs.jsonl": sha256_file(jobs_path),
    }
    if errors_path and errors_path.is_file() and errors_path.stat().st_size:
        checksums["details_errors.jsonl"] = sha256_file(errors_path)
    revision = hashlib.sha256(
        json.dumps(checksums, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return revision, checksums


def _known_checksum(source_root: Path) -> str | None:
    manifests = sorted(source_root.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            files = manifest["files"]
            if all(
                (manifest_path.parent / filename).is_file()
                and sha256_file(manifest_path.parent / filename) == checksum
                for filename, checksum in files.items()
            ):
                return manifest["revision"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def _validate_jsonl(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row {line_number} must be an object")
            count += 1
    if count == 0:
        raise ValueError("Crawler produced no JSONL records")
    return count


def snapshot(source_id: str, source_url: str, listings_path: str | Path,
             jobs_path: str | Path, errors_path: str | Path | None = None,
             output_root: str | Path = "data/raw/jobs",
             log_path: str | Path = DEFAULT_LOG, crawl_args: list[str] | None = None) -> dict:
    source_id = _safe_component(source_id, "source_id")
    listings_path = Path(listings_path)
    jobs_path = Path(jobs_path)
    errors_path = Path(errors_path) if errors_path else None
    started = datetime.now(timezone.utc).isoformat()
    try:
        listing_count = _validate_jsonl(listings_path)
        job_count = _validate_jsonl(jobs_path)
        descriptions = 0
        with jobs_path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip() and (json.loads(line).get("description") or "").strip():
                    descriptions += 1
        error_count = _validate_jsonl(errors_path) if errors_path and errors_path.exists() and errors_path.stat().st_size else 0
        revision, checksums = _snapshot_revision(listings_path, jobs_path, errors_path)
        source_root = Path(output_root) / source_id
        previous_revision = _known_checksum(source_root)
        if previous_revision == revision:
            event = {"status": "SKIPPED_UNCHANGED", "source_id": source_id,
                     "revision": revision, "records": job_count,
                     "descriptions": descriptions, "source_url": source_url,
                     "collected_at": started}
            _log(log_path, event)
            return event

        destination = source_root / revision
        destination.mkdir(parents=True, exist_ok=True)
        for source_file, filename in ((listings_path, "listings.jsonl"), (jobs_path, "jobs.jsonl")):
            (destination / filename).write_bytes(source_file.read_bytes())
        if "details_errors.jsonl" in checksums and errors_path:
            (destination / "details_errors.jsonl").write_bytes(errors_path.read_bytes())
        manifest = {
            "dataset": "jobs.jsonl",
            "file": "jobs.jsonl",
            "source_id": source_id,
            "source_url": source_url,
            "revision": revision,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "files": checksums,
            "sizes_bytes": {
                filename: (destination / filename).stat().st_size
                for filename in checksums
            },
            "size_bytes": (destination / "jobs.jsonl").stat().st_size,
            "sha256": checksums["jobs.jsonl"],
            "records": job_count,
            "listing_records": listing_count,
            "records_with_description": descriptions,
            "description_coverage": round(descriptions / job_count, 6),
            "description_errors": error_count,
            "crawl_args": crawl_args or [],
        }
        write_manifest(manifest, destination / "manifest.json")
        event = {**manifest, "status": "COLLECTED", "path": str(destination)}
        _log(log_path, event)
        return event
    except Exception as exc:
        event = {"status": "FAILED", "source_id": source_id, "source_url": source_url,
                 "error": f"{type(exc).__name__}: {exc}", "collected_at": started}
        _log(log_path, event)
        LOGGER.exception("Crawler collection failed for %s", source_id)
        return event


def run_listing_crawler(source_id: str, crawl_args: list[str],
                        log_path: str | Path = DEFAULT_LOG) -> dict:
    if source_id not in CRAWLERS:
        raise ValueError(f"Unsupported source: {source_id}")
    staging = Path("data/staging")
    staging.mkdir(parents=True, exist_ok=True)
    listing_path = staging / f"{source_id}-listings.jsonl"
    listing_path.unlink(missing_ok=True)
    (staging / f"{source_id}-jobs.jsonl").unlink(missing_ok=True)
    (staging / f"{source_id}-details-errors.jsonl").unlink(missing_ok=True)
    command = [sys.executable, "-m", f"crawlers.{source_id}", *crawl_args,
               "--out", str(listing_path)]
    try:
        completed = _run_subprocess(command)
        if completed.returncode != 0:
            raise RuntimeError(f"Crawler exited with status {completed.returncode}")
        records = _validate_jsonl(listing_path)
        event = {"status": "LISTINGS_READY", "source_id": source_id,
                 "source_url": CRAWLERS[source_id], "listing_records": records,
                 "path": str(listing_path),
                 "collected_at": datetime.now(timezone.utc).isoformat()}
        _log(log_path, event)
        return event
    except Exception as exc:
        event = {"status": "FAILED", "source_id": source_id, "source_url": CRAWLERS[source_id],
                 "error": f"{type(exc).__name__}: {exc}",
                 "collected_at": datetime.now(timezone.utc).isoformat()}
        _log(log_path, event)
        LOGGER.exception("Crawler run failed for %s", source_id)
        return event


def run_description_fetch(source_id: str, crawl_args: list[str], output_root: str | Path,
                          log_path: str | Path) -> dict:
    if source_id not in CRAWLERS:
        raise ValueError(f"Unsupported source: {source_id}")
    staging = Path("data/staging")
    listing_path = staging / f"{source_id}-listings.jsonl"
    jobs_path = staging / f"{source_id}-jobs.jsonl"
    errors_path = staging / f"{source_id}-details-errors.jsonl"
    try:
        if not listing_path.is_file():
            raise FileNotFoundError(f"Run make crawl-{source_id} first; missing {listing_path}")
        details_command = [sys.executable, "-m", "src.collection.fetch_job_details",
                           "--in", str(listing_path), "--out", str(jobs_path),
                           "--errors", str(errors_path)]
        if "--headless" in crawl_args:
            details_command.append("--headless")
        details_result = _run_subprocess(details_command)
        if details_result.returncode != 0:
            raise RuntimeError(f"Description fetch exited with status {details_result.returncode}")
        event = snapshot(source_id, CRAWLERS[source_id], listing_path, jobs_path,
                         errors_path, output_root, log_path, crawl_args)
        if event["status"] in {"COLLECTED", "SKIPPED_UNCHANGED"}:
            for path in (listing_path, jobs_path, errors_path):
                path.unlink(missing_ok=True)
        return event
    except Exception as exc:
        event = {"status": "FAILED", "source_id": source_id, "source_url": CRAWLERS[source_id],
                 "error": f"{type(exc).__name__}: {exc}",
                 "collected_at": datetime.now(timezone.utc).isoformat()}
        _log(log_path, event)
        LOGGER.exception("Description fetch failed for %s", source_id)
        return event


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=sorted(CRAWLERS))
    parser.add_argument("--phase", choices=("listings", "descriptions"), default="listings")
    parser.add_argument("--output-root", default="data/raw/jobs")
    parser.add_argument("--log-path", default=str(DEFAULT_LOG))
    args, crawler_args = parser.parse_known_args()
    if crawler_args[:1] == ["--"]:
        crawler_args = crawler_args[1:]
    logging.basicConfig(level=logging.INFO)
    if args.phase == "listings":
        event = run_listing_crawler(args.source, crawler_args, args.log_path)
    else:
        event = run_description_fetch(args.source, crawler_args, args.output_root, args.log_path)
    if event["status"] == "FAILED":
        raise SystemExit(1)
    print(json.dumps(event, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
