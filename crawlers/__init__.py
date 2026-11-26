"""Job-board crawler package.

Each <site>.py is a listing crawler run as `python -m crawlers.<site>`; the
CLI takes --out (and optional --pages, --headless, --no-dns-pin) and writes
JSONL rows with at least: job_url, title, company, location, site.
"""
