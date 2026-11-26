"""Fetch the full job description for each TopCV URL.

Resumable: the output file is rewritten in batches and doubles as a
checkpoint.
"""

import argparse
import json
import time
from pathlib import Path

from bs4 import BeautifulSoup
from tqdm import tqdm

from crawlers.base import read_jsonl
from crawlers.browser import USER_AGENT

RETRIES = 5
RETRY_DELAY = 2.0
BATCH_SIZE = 200


def _get_job_description_text(soup: BeautifulSoup) -> dict:
    boilerplate = (
        "Tiếp lợi thế",
        "Hệ sinh thái HR Tech",
        "TopCV hiểu rõ",
        "Định vị bản thân",
    )
    best = ""
    for el in soup.select("div, section"):
        txt = el.get_text("\n", strip=True)
        if len(txt) > 400 and not any(b in txt for b in boilerplate):
            if len(txt) > len(best):
                best = txt
    if not best:
        raise RuntimeError("no description found")
    return {"description": best}


def get_description(soup: BeautifulSoup) -> dict:
    return _get_job_description_text(soup)


def is_cloudflare(soup: BeautifulSoup) -> bool:
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").lower()
    if any(t in title for t in ("just a moment", "attention required", "cloudflare")):
        return True
    if soup.select_one(
        "#challenge-form, #cf-challenge-running, .cf-browser-verification, "
        "#challenge-body-text, div.cf-wrapper, script[src*='challenges.cloudflare.com']"
    ):
        return True
    text = soup.get_text(" ", strip=True)[:1500].lower()
    markers = (
        "checking your browser before accessing",
        "cf-browser-verification",
        "enable javascript and cookies to continue",
        "verify you are human",
        "performance & security by cloudflare",
        "needs to review the security of your connection",
    )
    return any(m in text for m in markers)


EXTRACTOR = _get_job_description_text


def description_complete(row: dict) -> bool:
    return bool((row.get("description") or "").strip())


class CloudflareDetected(Exception):
    pass


def fetch_job(page, row: dict) -> dict:
    page.goto(row["job_url"], wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)
    soup = BeautifulSoup(page.content(), "lxml")
    if is_cloudflare(soup):
        raise CloudflareDetected()
    detail = _get_job_description_text(soup)
    if not (detail.get("description") or "").strip():
        raise RuntimeError("empty description")
    return {**row, **detail}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch full TopCV job bodies")
    parser.add_argument("--in", dest="src", type=str, default="data/dedup.jsonl")
    parser.add_argument("--out", type=str, default="data/full.jsonl")
    parser.add_argument("--errors", type=str, default="data/details-errors.jsonl")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    rows = read_jsonl(args.src)
    out = Path(args.out)
    err_path = Path(args.errors)
    out.parent.mkdir(parents=True, exist_ok=True)
    err_path.parent.mkdir(parents=True, exist_ok=True)

    results = {}
    if out.exists():
        for r in read_jsonl(out):
            if r.get("job_url") and (r.get("description") or "").strip():
                results[r["job_url"]] = r

    todo = [
        r
        for r in rows
        if r.get("job_url") and not description_complete(results.get(r["job_url"], r))
    ]
    if args.limit:
        todo = todo[: args.limit]
    print(
        f"{len(rows)} total, {len(results)} already fetched, {len(todo)} to fetch",
        flush=True,
    )

    errors = []

    def flush():
        with out.open("w", encoding="utf-8") as fh:
            for row in rows:
                merged = results.get(row["job_url"], row)
                fh.write(json.dumps(merged, ensure_ascii=False) + "\n")

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser_obj = ctx = page = None

    def open_browser():
        nonlocal browser_obj, ctx, page
        browser_obj = pw.chromium.launch(
            channel="chrome",
            headless=args.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser_obj.new_context(user_agent=USER_AGENT)
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = ctx.new_page()

    def close_browser():
        nonlocal browser_obj, ctx, page
        for obj in (ctx, browser_obj):
            if obj:
                try:
                    obj.close()
                except Exception:
                    pass
        browser_obj = ctx = page = None

    open_browser()
    try:
        with tqdm(total=len(todo), desc="topcv", unit="job") as pbar:
            for i, row in enumerate(todo, 1):
                merged = None
                err = None
                for attempt in range(RETRIES):
                    try:
                        merged = fetch_job(page, row)
                        break
                    except CloudflareDetected:
                        print(
                            f"[cloudflare] reopening browser for {row['job_url']}",
                            flush=True,
                        )
                        close_browser()
                        time.sleep(2)
                        open_browser()
                        err = f"cloudflare (attempt {attempt + 1})"
                    except Exception as exc:
                        err = f"{type(exc).__name__}: {str(exc)[:200]}"
                        time.sleep(RETRY_DELAY * (attempt + 1))
                if merged is not None:
                    results[row["job_url"]] = merged
                else:
                    errors.append(
                        {
                            "job_url": row["job_url"],
                            "site": "topcv",
                            "error": err,
                        }
                    )
                if i % BATCH_SIZE == 0:
                    flush()
                pbar.update(1)
        flush()
    finally:
        close_browser()
        pw.stop()

    if err_path.exists():
        err_path.unlink()
    if errors:
        with err_path.open("w", encoding="utf-8") as fh:
            for e in errors:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(
        f"fetched {len(results)} descriptions total, {len(errors)} errors", flush=True
    )
    print(f"full -> {out}, errors -> {err_path}")


if __name__ == "__main__":
    main()
