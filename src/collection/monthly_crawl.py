"""Bounded monthly TopCV/ITviec crawl for an ephemeral CI runner.

Each invocation is a self-contained snapshot. It does not assume that ignored
local datasets exist in GitHub Actions, and it never sends data to an LLM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from crawlers.base import read_jsonl
from crawlers.browser import persistent_chromium
from src.collection.targeted_role_crawl import SEARCHES, canonical, crawl_site
from src.preparation.pipeline import run as prepare

ROOT = Path(__file__).resolve().parents[2]


def prepare_snapshot(jobs_path: Path, out_dir: Path) -> dict:
    """Run the same preparation pipeline as local aggregate runs."""
    if not jobs_path.exists() or not jobs_path.stat().st_size:
        return {'downloaded_descriptions': 0, 'status': {}, 'by_source': {},
                'eligible_primary_roles': {}}
    destination = out_dir/'prepared'
    run_id = 'monthly_' + hashlib.sha256(str(out_dir.resolve()).encode()).hexdigest()[:16]
    prepare(ROOT, run_id, execute=True,
            inputs=(jobs_path,), output_dir=destination)
    summary = json.loads((destination/'summary.json').read_text(encoding='utf-8'))
    records = pq.read_table(destination/'master_jds.parquet',
                            columns=['eligibility_status', 'primary_role']).to_pylist()
    roles = Counter(row['primary_role'] for row in records if row['eligibility_status'] == 'eligible')
    sources = {site: sum(statuses.values()) for site, statuses in summary['by_source'].items()}
    return {'downloaded_descriptions': len(read_jsonl(jobs_path)),
            'status': summary['counts'], 'by_source': sources,
            'eligible_primary_roles': dict(roles)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--pages-per-role', type=int, default=2)
    parser.add_argument('--pages-per-query', type=int, default=3)
    parser.add_argument('--details-per-role-source', type=int, default=15)
    parser.add_argument('--delay', type=float, default=2.0)
    parser.add_argument('--sources', default='topcv,itviec')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if min(args.pages_per_role, args.pages_per_query, args.details_per_role_source) < 1 or args.delay < 0:
        parser.error('budgets must be positive and delay must be nonnegative')
    sources = [site.strip() for site in args.sources.split(',') if site.strip()]
    if not sources or len(set(sources)) != len(sources) or any(s not in {'topcv', 'itviec'} for s in sources):
        parser.error('sources must be topcv and/or itviec without duplicates')
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    plan = {'created_at': datetime.now(timezone.utc).isoformat(),
            'sources': sources, 'roles': list(SEARCHES), 'pages_per_role': args.pages_per_role,
            'pages_per_query': args.pages_per_query,
            'details_per_role_source': args.details_per_role_source, 'delay_seconds': args.delay,
            'note': 'Monthly snapshot; no prior local dataset available on GitHub runner.'}
    (out/'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    jobs, errors, events = [out/name for name in ('jobs.jsonl', 'errors.jsonl', 'events.jsonl')]
    state = {'next_page': {}, 'exhausted': [], 'blocked': {}}
    known: set[str] = {canonical(row['job_url']) for row in read_jsonl(jobs)} if jobs.exists() else set()
    with persistent_chromium(out/'chrome-profile', headless=True, hosts=[]) as browser:
        page = browser.new_page()
        for role in SEARCHES:
            for site in sources:
                if site in state['blocked']:
                    continue
                count = crawl_site(page, role=role, site=site,
                                   budget=args.details_per_role_source,
                                   pages=args.pages_per_role, state=state, known=known,
                                   jobs_path=jobs, errors_path=errors, events_path=events,
                                   delay=args.delay, max_pages_per_query=args.pages_per_query)
                print(f'[monthly] {role} / {site}: {count} JDs', flush=True)
    stats = prepare_snapshot(jobs, out)
    result = {**plan, **stats, 'blocked_sources': state['blocked'],
              'exhausted_queries': len(state['exhausted'])}
    (out/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if stats['downloaded_descriptions'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
