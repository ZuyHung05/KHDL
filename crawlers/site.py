from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from .base import Board, read_jsonl, write_all_jsonl
from .config import load_crawler_config

ROOT = Path(__file__).resolve().parents[1]


def load_sites() -> dict[str, dict[str, Any]]:
    return load_crawler_config().get("sites", {})


def build_board(site_id: str, extractor, **overrides) -> Board:
    sites = load_sites()
    if site_id not in sites:
        raise ValueError(f"Unknown site {site_id!r}; configure it in configs/crawlers.yaml")
    cfg = sites[site_id]
    wait = cfg.get("wait", {})
    cf = cfg.get("cloudflare", {})
    base = dict(
        site=site_id,
        url=cfg["url"],
        host=cfg.get("host", _host_of(cfg["url"])),
        profile=cfg.get("profile", f"data/browser_profiles/{site_id}"),
        listing_selector=cfg.get("listing_selector", ""),
        extractor=extractor,
        cloudflare_markers=tuple(cf.get("markers", [])),
        cloudflare_dom_selector=cf.get("dom_selector", ""),
        cf_timeout_ms=cf.get("timeout_ms", 60000),
        paged_url_template=cfg.get("paged_url_template"),
        first_page_wait_ms=wait.get("first_page_ms", 1500),
        per_page_wait_ms=wait.get("per_page_ms", 1500),
        render_wait_ms=wait.get("render_ms", 1200),
        pacing_ms=wait.get("pacing_ms", 0),
        stop_after_consecutive_no_new=cfg.get("stop_after_consecutive_no_new", 0),
        resume=cfg.get("resume", False),
        poll_interval_s=cfg.get("poll_interval_s", 2.0),
    )
    base.update(overrides)
    return Board(**base)


def _host_of(url: str) -> str:
    import re

    return re.sub(r"^https?://", "", url).split("/")[0]


def parse_args(site_id: str, description: str, defaults: dict) -> argparse.Namespace:
    sites = load_sites()
    site = sites.get(site_id, {})
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--pages", type=int, default=int(defaults.get("pages", site.get("default_pages", 30))))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--out", default=defaults.get("out", f"{site_id}-listings.jsonl"))
    parser.add_argument("--profile", default=site.get("profile", f"data/browser_profiles/{site_id}"))
    parser.add_argument("--no-dns-pin", action="store_true", help="disable --host-resolver-rules")
    if site.get("resume", False):
        parser.add_argument("--resume", action="store_true", help="merge existing output and continue")
    return parser.parse_args()


def resume_rows(out: str | Path) -> dict[str, dict[str, Any]]:
    existing: dict[str, dict[str, Any]] = {}
    try:
        for r in read_jsonl(out):
            key = r.get("job_url") or r.get("url")
            if key:
                existing[key] = r
    except (OSError, ValueError) as exc:
        logging.getLogger("it4930.crawlers.site").warning(
            "could not read existing output for resume: %s", exc
        )
    return existing


def run(board: Board, *, out: str | Path, pages: int, headless: bool,
        hosts: list[str], existing: dict[str, dict[str, Any]] | None = None,
        resume_from: int = 1, clean: bool = True) -> None:
    from .browser import persistent_chromium

    logging.basicConfig(level=logging.INFO)
    with persistent_chromium(board.profile, headless=headless, hosts=hosts) as ctx:
        page = ctx.new_page()
        rows = board.crawl(page, pages, existing=existing, resume_from=resume_from)
    write_all_jsonl(out, rows)
    logging.getLogger("it4930.crawlers.site").info(
        "wrote %d listings to %s", len(rows), out
    )
