from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("it4930.crawlers.base")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_all_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def log_done(out: str | Path, count: int) -> None:
    LOGGER.info("wrote %d listings to %s", count, out)


def throttle(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


Extractor = Callable[[Any], list[dict[str, Any]]]


@dataclass
class Board:
    url: str
    host: str
    profile: str
    listing_selector: str
    extractor: Extractor
    site: str
    cloudflare_markers: tuple[str, ...] = ()
    cloudflare_dom_selector: str = ""
    cf_timeout_ms: int = 60000
    paged_url_template: str | None = None
    first_page_wait_ms: int = 1500
    per_page_wait_ms: int = 1500
    render_wait_ms: int = 1200
    pacing_ms: int = 0
    stop_after_consecutive_no_new: int = 0
    resume: bool = False
    clean: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    poll_interval_s: float = 2.0

    def page_url(self, n: int) -> str:
        if n > 1 and self.paged_url_template:
            return f"{self.url}{self.paged_url_template.format(n=n)}"
        return self.url

    def is_cloudflare(self, page) -> bool:
        title = (page.title() or "").lower()
        if any(m in title for m in self.cloudflare_markers):
            return True
        return bool(self.cloudflare_dom_selector and page.locator(self.cloudflare_dom_selector).count())

    def _wait_cloudflare_clear(self, page) -> bool:
        deadline = time.time() + self.cf_timeout_ms / 1000.0
        while time.time() < deadline:
            if self.is_cloudflare(page):
                time.sleep(self.poll_interval_s)
                continue
            page.wait_for_timeout(self.render_wait_ms)
            if page.locator(self.listing_selector).count() > 0:
                return True
            time.sleep(self.poll_interval_s)
        LOGGER.warning("Cloudflare challenge did not clear within %sms.", self.cf_timeout_ms)
        return False

    def crawl(
        self,
        page,
        pages: int,
        existing: dict[str, dict[str, Any]] | None = None,
        resume_from: int = 1,
    ) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = dict(existing or {})
        dupes = 0
        consecutive_no_new = 0
        for n in range(resume_from, resume_from + pages):
            page.goto(self.page_url(n), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(self.first_page_wait_ms if n == resume_from else self.per_page_wait_ms)
            if self.is_cloudflare(page):
                LOGGER.warning("Cloudflare on page %d; waiting for clearance...", n)
                if not self._wait_cloudflare_clear(page):
                    LOGGER.warning("Cloudflare did not clear on page %d; stopping.", n)
                    break
            rows = self.extractor(page)
            prev = len(seen)
            for r in rows:
                key = r.get("job_url") or r.get("url")
                if not key:
                    continue
                stored = seen.get(key)
                if stored is None:
                    seen[key] = r
                else:
                    dupes += 1
            added = len(seen) - prev
            LOGGER.info("page %d: %d rows, %d new (total %d)", n, len(rows), added, len(seen))
            if not rows:
                LOGGER.info("no cards on page %d; reached end of results.", n)
                break
            consecutive_no_new = consecutive_no_new + 1 if added == 0 else 0
            if self.stop_after_consecutive_no_new and consecutive_no_new >= self.stop_after_consecutive_no_new:
                LOGGER.info("no new jobs in %d pages; results exhausted at page %d.", consecutive_no_new, n)
                break
            throttle(self.pacing_ms / 1000.0)
        LOGGER.info("done: %d unique listings (%d duplicate links skipped)", len(seen), dupes)
        out = list(seen.values())
        if self.clean:
            out = [self.clean(r) for r in out]
        return out
