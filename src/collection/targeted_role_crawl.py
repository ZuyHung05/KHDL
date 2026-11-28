"""Crawl scarce roles, prepare fetched JDs, and remeasure role gaps.

One headless Chrome context is reused for the entire invocation. The run has
finite page/detail/cycle budgets and stops a source when challenged.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pyarrow.parquet as pq
from bs4 import BeautifulSoup

from crawlers.base import append_jsonl, read_jsonl
from crawlers.browser import persistent_chromium
from crawlers.topcv import extract_rows as extract_topcv_rows
from src.collection.topcv_detail import get_description, is_cloudflare as topcv_cloudflare
from src.preparation.pipeline import OUTSIDE, restore_topcv, run as prepare
from src.preparation.taxonomy import enrich
from src.preparation.role_report import PATTERNS

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = ROOT / 'data/inputs/legacy_import_20261127.parquet'
DEFAULT_PREPARED = ROOT / 'data/curated/preparation/current/master_jds.parquet'
SEARCHES = {
    'Cloud': {'topcv': ['cloud-engineer', 'cloud'], 'itviec': ['cloud', 'aws', 'azure']},
    'UI/UX': {'topcv': ['ui-ux', 'ux-designer'], 'itviec': ['ui-ux', 'product-design', 'figma']},
    'Cybersecurity': {'topcv': ['cyber-security', 'bao-mat'], 'itviec': ['security', 'cybersecurity', 'pentest']},
    'System/Network/IT Support': {'topcv': ['it-support', 'network-engineer'], 'itviec': ['it-support', 'system-administrator', 'network']},
    'Embedded': {'topcv': ['embedded-engineer', 'he-thong-nhung'], 'itviec': ['embedded', 'firmware']},
    'ERP/SAP': {'topcv': ['sap', 'erp'], 'itviec': ['sap', 'erp', 'odoo']},
    'DevOps/SRE': {'topcv': ['devops', 'site-reliability-engineer'], 'itviec': ['devops']},
}
FAMILY = {role: family for family, roles in PATTERNS.items() for role in roles}
CITY = re.compile(r'\b(?:Ho Chi Minh|Ha Noi|Da Nang|Can Tho|Hai Phong|Hanoi|HCM|HCMC)\b', re.I)
TITLE_HINTS = {
    'Cloud': r'cloud|đám mây', 'UI/UX': r'ui[ /-]?ux|ux|ui design|product design',
    'Cybersecurity': r'cyber|security|bảo mật|an toàn thông tin',
    'System/Network/IT Support': r'it support|helpdesk|network|system|hệ thống|mạng',
    'Embedded': r'embedded|nhúng|firmware', 'ERP/SAP': r'\berp\b|\bsap\b',
    'DevOps/SRE': r'devops|devsecops|site reliability|\bsre\b',
}


def canonical(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip('/'), '', ''))


def role_counts(master: Path) -> Counter:
    rows = pq.read_table(master, columns=['eligibility_status', 'primary_role']).to_pylist()
    return Counter(r['primary_role'] for r in rows if r['eligibility_status'] == 'eligible')


def gaps(counts: Counter, target: int) -> list[dict]:
    return sorted(({'family': FAMILY[role], 'role': role, 'current': counts[role],
                    'target': target, 'missing': max(0, target - counts[role])}
                   for role in SEARCHES), key=lambda r: (-r['missing'], r['role']))


def extract_itviec_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html, 'lxml')
    rows = []
    for card in soup.select('.job-card'):
        title = card.select_one('h3 a[href*="/it-jobs/"]')
        if not title or not title.get('href'):
            continue
        company = next((a for a in card.select('a[href*="/companies/"]')
                        if a.get_text(' ', strip=True)), None)
        url = canonical(title['href'])
        if urlsplit(url).hostname not in {'itviec.com', 'www.itviec.com'}:
            continue
        cities = list(dict.fromkeys(m.group() for m in CITY.finditer(card.get_text(' ', strip=True))))
        rows.append({'job_url': url, 'site': 'itviec', 'title': title.get_text(' ', strip=True),
                     'company': company.get_text(' ', strip=True) if company else '',
                     'location': ' - '.join(cities)})
    return rows


def extract_itviec_detail(html: str) -> dict:
    soup = BeautifulSoup(html, 'lxml')
    sections = {}
    for heading in soup.select('div.paragraph.text-break > h2'):
        key = heading.get_text(' ', strip=True).casefold()
        text = heading.parent.get_text('\n', strip=True)
        sections[key] = text[len(heading.get_text('\n', strip=True)):].strip()
    duties = sections.get('job description') or sections.get('mô tả công việc') or ''
    requirements = sections.get('your skills and experience') or sections.get('kỹ năng và kinh nghiệm') or ''
    benefits = sections.get("why you'll love working here") or sections.get('quyền lợi') or ''
    if len(duties) < 80 or len(requirements) < 40:
        raise ValueError('Itviec JD sections are missing or too short')
    description = '\n'.join(['Job Description', duties, 'Candidate Requirements', requirements,
                             'Benefits', benefits])
    return {'duties': duties, 'requirements': requirements, 'benefits': benefits,
            'description': description, 'parse_status': 'structured'}


def extract_topcv_detail(html: str) -> dict:
    soup = BeautifulSoup(html, 'lxml')
    if topcv_cloudflare(soup):
        raise Blocked('cloudflare_detail')
    description = get_description(soup)['description']
    duties, requirements, benefits, status = restore_topcv(description)
    if status != 'restored':
        if len(description) < 200 or 'Mô tả công việc' not in description:
            raise ValueError(f'TopCV JD could not be parsed: {status}')
        duties, requirements, benefits, status = description, '', '', 'partial'
    return {'description': description, 'duties': duties, 'requirements': requirements,
            'benefits': benefits, 'parse_status': status}


class Blocked(Exception):
    pass


def is_blocked(page, response) -> bool:
    if response and response.status in {403, 429}:
        return True
    if response and response.headers.get('cf-mitigated') == 'challenge':
        return True
    title = page.title().casefold()
    return ('just a moment' in title or 'attention required' in title
            or bool(page.locator('#challenge-form, #cf-challenge-running, .cf-browser-verification').count()))


def search_url(site: str, term: str, page: int) -> str:
    if site == 'topcv':
        base = f'https://www.topcv.vn/tim-viec-lam-{term}'
        return base if page == 1 else f'{base}?page={page}'
    base = f'https://itviec.com/it-jobs/{term}'
    return base if page == 1 else f'{base}?page={page}&source=search_job'


def navigate(page, url: str):
    response = page.goto(url, wait_until='domcontentloaded', timeout=45000)
    page.wait_for_timeout(1200)
    if is_blocked(page, response):
        raise Blocked(f'challenge_or_rate_limit: {url}')
    if response and response.status >= 400:
        raise ValueError(f'HTTP {response.status}: {url}')
    return response


def listing_rows(page, site: str) -> list[dict]:
    rows = extract_topcv_rows(page) if site == 'topcv' else extract_itviec_rows(page.content())
    return [{**row, 'job_url': canonical(row['job_url']), 'site': site} for row in rows if row.get('job_url')]


def score_title(row: dict, role: str) -> int:
    title = row.get('title', '')
    if OUTSIDE.search(title):
        return 2
    if role == 'Cloud' and re.search(r'salesforce|sales cloud|marketing cloud', title, re.I):
        return 2
    if role == 'System/Network/IT Support' and re.search(r'\bbridge\b|\bbrse\b', title, re.I):
        return 2
    result = enrich({'title': title, 'duties': '', 'requirements': ''})
    if result['primary_role'] == role:
        return 0
    if result['primary_role'] not in {'unknown', role}:
        return 2
    if re.search(TITLE_HINTS[role], title, re.I):
        return 1
    return 2


def save_gaps(path: Path, counts: Counter, target: int, cycle: int) -> list[dict]:
    items = gaps(counts, target)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['priority', 'family', 'role', 'current', 'target', 'missing'])
        writer.writeheader()
        writer.writerows({'priority': i, **item} for i, item in enumerate(items, 1))
    lines = [f'# Nghề cần bổ sung sau vòng {cycle}', '',
             f'Mục tiêu: ít nhất {target} JD phù hợp, có description, cho mỗi nghề.', '',
             '| Ưu tiên | Nhóm | Nghề | Hiện có | Còn thiếu |', '|---:|---|---|---:|---:|']
    lines += [f"| {i} | {item['family']} | {item['role']} | {item['current']} | {item['missing']} |"
              for i, item in enumerate(items, 1)]
    lines += ['', '![Số JD hiện có so với mục tiêu](role_priority.png)']
    path.with_suffix('.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ordered = items[::-1]
    y = range(len(ordered))
    ax.barh(y, [r['current'] for r in ordered], color='#168f7a', label='JD phù hợp')
    ax.barh(y, [r['missing'] for r in ordered], left=[r['current'] for r in ordered],
            color='#e6aa52', label='Còn thiếu tới mục tiêu')
    for i, row in enumerate(ordered):
        ax.text(max(target, row['current'])+1, i, f"{row['current']}/{target}", va='center')
    ax.set_yticks(list(y), [r['role'] for r in ordered]); ax.set_xlim(0, max(target, max(r['current'] for r in ordered))*1.18)
    ax.set_xlabel('Số JD phù hợp có nghề cụ thể'); ax.set_title(f'Tiến độ theo nghề sau vòng {cycle}')
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -.12), ncol=2); fig.tight_layout()
    fig.savefig(path.with_suffix('.png'), dpi=170, bbox_inches='tight'); plt.close(fig)
    print(f'\nCycle {cycle}: role gaps (target {target})', flush=True)
    for item in items:
        print(f"  {item['role']}: {item['current']}/{target}, missing {item['missing']}", flush=True)
    return items


def write_state(path: Path, state: dict) -> None:
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def choose_query(state: dict, role: str, site: str, max_pages_per_query: int):
    terms = SEARCHES[role][site]
    for term in terms:
        key = f'{role}|{site}|{term}'
        if state['next_page'].get(key, 1) > max_pages_per_query and key not in state['exhausted']:
            state['exhausted'].append(key)
        if key not in state['exhausted']:
            return term, key, state['next_page'].get(key, 1)
    return None


def crawl_site(page, *, role: str, site: str, budget: int, pages: int, state: dict,
               known: set[str], jobs_path: Path, errors_path: Path, events_path: Path,
               delay: float, max_pages_per_query: int) -> int:
    fetched = 0
    used_pages = 0
    while fetched < budget and used_pages < pages:
        chosen = choose_query(state, role, site, max_pages_per_query)
        if not chosen:
            break
        term, key, number = chosen
        url = search_url(site, term, number)
        try:
            navigate(page, url)
            cards = listing_rows(page, site)
        except Blocked as exc:
            state['blocked'][site] = str(exc)
            append_jsonl(events_path, {'event': 'blocked', 'site': site, 'role': role, 'url': url})
            print(f'[blocked] {site}: {exc}', flush=True)
            break
        except Exception as exc:
            state['exhausted'].append(key)
            append_jsonl(errors_path, {'site': site, 'role': role, 'url': url, 'error': repr(exc)[:300]})
            print(f'[page error] {site} {role}: {exc}', flush=True)
            continue
        state['next_page'][key] = number + 1
        used_pages += 1
        append_jsonl(events_path, {'event': 'page', 'site': site, 'role': role, 'term': term,
                                   'page': number, 'cards': len(cards), 'url': url})
        print(f'[page] {site} {role} {term} #{number}: {len(cards)} cards', flush=True)
        if not cards:
            state['exhausted'].append(key)
            continue
        cards = [card for card in cards if score_title(card, role) <= 1]
        cards.sort(key=lambda row: score_title(row, role))
        for card in cards:
            if fetched >= budget:
                # Revisit remaining cards on this page in the next cycle.
                state['next_page'][key] = number
                break
            job_url = card['job_url']
            if job_url in known:
                continue
            known.add(job_url)
            try:
                navigate(page, job_url)
                detail = (extract_topcv_detail(page.content()) if site == 'topcv'
                          else extract_itviec_detail(page.content()))
                row = {**card, **detail, 'search_role': role,
                       'fetched_at': datetime.now().astimezone().isoformat()}
                append_jsonl(jobs_path, row)
                fetched += 1
                print(f'[detail] {site} {role}: {card["title"][:70]}', flush=True)
            except Blocked as exc:
                state['blocked'][site] = str(exc)
                append_jsonl(events_path, {'event': 'blocked', 'site': site, 'role': role, 'url': job_url})
                print(f'[blocked] {site}: {exc}', flush=True)
                return fetched
            except Exception as exc:
                append_jsonl(errors_path, {'site': site, 'role': role, 'url': job_url,
                                           'error': repr(exc)[:300]})
            time.sleep(delay)
    return fetched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=ROOT/'data/targeted_crawl/roles_20261127')
    parser.add_argument('--baseline-run', type=Path, default=DEFAULT_PREPARED)
    parser.add_argument('--baseline-input', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--target', type=int, default=80)
    parser.add_argument('--max-cycles', type=int, default=5)
    parser.add_argument('--max-pages-per-role', type=int, default=2)
    parser.add_argument('--max-pages-per-query', type=int, default=5)
    parser.add_argument('--max-details-per-role', type=int, default=20)
    parser.add_argument('--delay', type=float, default=1.5)
    parser.add_argument('--sources', default='topcv,itviec')
    parser.add_argument('--roles', default='', help='Comma separated role names, default all gaps')
    parser.add_argument('--headed', action='store_true', help='Show Chrome for debugging; default is headless')
    parser.add_argument('--retry-blocked', action='store_true', help='Retry sources blocked in a previous invocation once')
    parser.add_argument('--refresh-searches', action='store_true', help='Recheck search page 1 on a later day; known URLs remain deduplicated')
    parser.add_argument('--reprepare', action='store_true', help='Rerun preparation for checkpointed jobs after rule changes')
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args(argv)
    if min(args.target, args.max_cycles, args.max_pages_per_role,
           args.max_pages_per_query, args.max_details_per_role) < 1:
        parser.error('target and budgets must be positive')
    sources = [x.strip() for x in args.sources.split(',') if x.strip()]
    if not sources or any(x not in {'topcv','itviec'} for x in sources):
        parser.error('sources must contain topcv and/or itviec')
    selected = {x.strip() for x in args.roles.split(',') if x.strip()} or set(SEARCHES)
    if selected - set(SEARCHES):
        parser.error(f'unknown roles: {sorted(selected-set(SEARCHES))}')
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    state_path = run_dir/'state.json'
    jobs_path, errors_path, events_path = [run_dir/name for name in ('jobs.jsonl','errors.jsonl','events.jsonl')]
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        'cycle': 0, 'next_page': {}, 'exhausted': [], 'blocked': {},
        'latest_run_id': None, 'stalled_cycles': 0, 'stop_reason': None}
    if args.retry_blocked:
        state['blocked'] = {}
    if args.refresh_searches:
        state['next_page'] = {}
        state['exhausted'] = []
        state['stalled_cycles'] = 0
    if state['stop_reason'] in {'no_eligible_gain_two_cycles', 'max_cycles_reached'}:
        state['stalled_cycles'] = 0
    state['stop_reason'] = None
    master = (ROOT/'data/curated/preparation'/state['latest_run_id']/'master_jds.parquet'
              if state['latest_run_id'] else args.baseline_run.resolve())
    if args.reprepare:
        if not jobs_path.exists():
            parser.error('--reprepare requires checkpointed jobs.jsonl')
        run_id = f'targeted_{run_dir.name}_refresh_{int(time.time())}'
        prepare(ROOT, run_id, execute=True, inputs=(args.baseline_input.resolve(), jobs_path))
        state['latest_run_id'] = run_id
        master = ROOT/'data/curated/preparation'/run_id/'master_jds.parquet'
        write_state(state_path, state)
    counts = role_counts(master)
    save_gaps(run_dir/'role_priority.csv', counts, args.target, state['cycle'])
    if args.plan_only:
        return 0
    known = {canonical(r['source_url']) for r in pq.read_table(master, columns=['source_url']).to_pylist()
             if r.get('source_url')}
    if jobs_path.exists():
        known.update(canonical(r['job_url']) for r in read_jsonl(jobs_path))
    with persistent_chromium(run_dir/'chrome-profile', headless=not args.headed, hosts=[]) as browser:
        page = browser.new_page()
        for cycle in range(state['cycle']+1, args.max_cycles+1):
            before = counts.copy()
            new_details = 0
            priorities = [item for item in gaps(counts,args.target) if item['missing'] and item['role'] in selected]
            if not priorities:
                state['stop_reason'] = 'target_reached'; break
            for item in priorities:
                role, deficit = item['role'], item['missing']
                pages = min(args.max_pages_per_role, max(1, math.ceil(deficit/25)))
                quota = min(args.max_details_per_role, max(4, math.ceil(deficit*1.5)))
                role_fetched = 0
                for i, site in enumerate(sources):
                    if site in state['blocked']:
                        continue
                    site_budget = (math.ceil(quota/len(sources)) if i < len(sources)-1
                                   else quota-role_fetched)
                    site_budget = max(1, site_budget)
                    got = crawl_site(page, role=role, site=site, budget=site_budget, pages=pages,
                                     state=state, known=known, jobs_path=jobs_path,
                                     errors_path=errors_path, events_path=events_path, delay=args.delay,
                                     max_pages_per_query=args.max_pages_per_query)
                    new_details += got
                    role_fetched += got
                    print(f'[role] {role} {site}: {got} descriptions', flush=True)
                    write_state(state_path, state)
            state['cycle'] = cycle
            if jobs_path.exists() and new_details:
                run_id = f'targeted_{run_dir.name}_{cycle}'
                print(f'[preparation] cycle {cycle}: {run_id}', flush=True)
                prepare(ROOT, run_id, execute=True, inputs=(args.baseline_input.resolve(), jobs_path))
                state['latest_run_id'] = run_id
                master = ROOT/'data/curated/preparation'/run_id/'master_jds.parquet'
                counts = role_counts(master)
            gains = {role: counts[role]-before[role] for role in SEARCHES if counts[role] > before[role]}
            append_jsonl(events_path, {'event': 'cycle', 'cycle': cycle, 'fetched_descriptions': new_details,
                                       'eligible_role_gains': gains, 'prepared_run': state['latest_run_id']})
            save_gaps(run_dir/'role_priority.csv', counts, args.target, cycle)
            state['stalled_cycles'] = 0 if gains else state['stalled_cycles']+1
            write_state(state_path, state)
            if all(counts[role] >= args.target for role in selected):
                state['stop_reason'] = 'target_reached'; break
            if all(site in state['blocked'] for site in sources):
                state['stop_reason'] = 'all_sources_blocked'; break
            remaining_queries = any(choose_query(state, item['role'], site, args.max_pages_per_query)
                                    for item in gaps(counts,args.target) if item['missing'] and item['role'] in selected
                                    for site in sources if site not in state['blocked'])
            if not remaining_queries:
                state['stop_reason'] = 'search_queries_exhausted'; break
        else:
            state['stop_reason'] = 'max_cycles_reached'
    write_state(state_path, state)
    remaining = [r for r in gaps(counts,args.target) if r['missing'] and r['role'] in selected]
    result = {'stop_reason': state['stop_reason'], 'cycles': state['cycle'], 'prepared_run': state['latest_run_id'],
              'remaining_roles': remaining, 'blocked_sources': state['blocked'], 'jobs_file': str(jobs_path)}
    (run_dir/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if not remaining else 2


if __name__ == '__main__':
    raise SystemExit(main())
