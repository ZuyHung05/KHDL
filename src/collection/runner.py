"""Manual GitHub dataset ingestion and coverage reporting."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import yaml
from .checksum import sha256_file

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
MAX_BYTES = 100 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')
        name = f.name
    os.replace(name, path)


def read_json(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def request(url):
    headers = {'User-Agent': 'IT4930-M01', 'Accept': 'application/vnd.github+json'}
    if os.environ.get('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    for attempt in range(3):
        try:
            return urlopen(Request(url, headers=headers), timeout=60)
        except (HTTPError, URLError, TimeoutError) as e:
            transient = not isinstance(e, HTTPError) or e.code == 429 or e.code >= 500
            if not transient or attempt == 2:
                raise
            delay = min(int(e.headers.get('Retry-After', '0') or 0), 60) if isinstance(e, HTTPError) else 0
            time.sleep(max(delay, 2 ** attempt))


def registry():
    config = yaml.safe_load((ROOT / 'configs/sources.yaml').read_text(encoding='utf-8'))
    allowed = {line.strip().removesuffix('.git').removeprefix('https://github.com/') for line in (ROOT / 'docs/nguondatagithub.txt').read_text(encoding='utf-8').splitlines() if line.strip()}
    ids = set()
    for s in config['sources']:
        if s['repository'] not in allowed or not re.fullmatch(r'[A-Za-z0-9_-]+', s['source_id']) or s['source_id'] in ids:
            raise ValueError('Invalid or unlisted source: ' + str(s))
        ids.add(s['source_id'])
        for item in s['files']:
            p = Path(item['path'])
            if p.is_absolute() or '..' in p.parts or item['format'] not in ('csv', 'json', 'jsonl'):
                raise ValueError('Invalid dataset path or format')
    return config['sources']


def file_id(path):
    return hashlib.sha256(path.encode()).hexdigest()[:16]


def rows(path, spec):
    with path.open(encoding=spec.get('encoding', 'utf-8-sig'), newline='') as f:
        if spec['format'] == 'csv':
            csv.field_size_limit(100000000)
            yield from csv.DictReader(f, strict=True)
        elif spec['format'] == 'json':
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError('JSON root must be an array')
            yield from data
        else:
            for line in f:
                if line.strip():
                    yield json.loads(line)


def validate(path, spec):
    count = titles = descriptions = missing = 0
    urls = []
    for row in rows(path, spec):
        if not isinstance(row, dict) or spec['title'] not in row or spec['description'] not in row:
            raise ValueError('Required title or description field missing')
        title = str(row.get(spec['title']) or '').strip()
        desc = str(row.get(spec['description']) or '').strip()
        count += 1
        titles += bool(title)
        descriptions += bool(desc)
        missing += not (title and desc)
        if spec.get('url') and row.get(spec['url']):
            urls.append(str(row[spec['url']]).strip())
    if not count or not titles or not descriptions:
        raise ValueError('Empty dataset or no usable titles/descriptions')
    return {'status': 'warning' if missing else 'passed', 'record_count': count,
            'description_nonempty_count': descriptions, 'missing_important_count': missing,
            'duplicate_url_count': len(urls) - len(set(urls)), 'warnings': [f'{missing} incomplete records'] if missing else [], 'errors': []}


def revision(source, spec):
    base = 'https://api.github.com/repos/' + source['repository']
    with request(base + '/commits/' + quote(source['ref'], safe='')) as r:
        commit = json.load(r)['sha']
    with request(base + '/contents/' + quote(spec['path'], safe='/') + '?ref=' + commit) as r:
        blob = json.load(r)['sha']
    return commit, blob


def log(run, task, status, stage, message):
    event = {'timestamp': now(), 'run_id': run, **task, 'stage': stage, 'status': status, 'message': message}
    path = ROOT / 'logs/m01.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')
    print(f'[{status}] {task["source_id"]} | {task["file_path"]} | {message}')
    return event


def ingest_issues(source, spec, run, dry=False):
    """Collect open issue bodies; publish only after every page succeeds."""
    sid, fp = source['source_id'], spec['path']
    fid = file_id(fp)
    task = {'task_id': uuid.uuid4().hex, 'source_id': sid, 'file_path': fp, 'attempt': 1}
    root = DATA / 'raw' / sid
    latest_path = root / 'latest.json'
    try:
        if dry:
            print(f'[PENDING] {sid} | {fp} | Would fetch open issues')
            return {'status': 'PENDING', **task, 'message': 'Would fetch open issues'}
        stage = DATA / 'staging' / run / sid / fid
        stage.mkdir(parents=True, exist_ok=True)
        staged = stage / Path(fp).name
        url = f'https://api.github.com/repos/{source["repository"]}/issues?state=open&per_page=100&sort=created&direction=asc'
        seen, count, missing = set(), 0, 0
        with staged.open('w', encoding='utf-8') as out:
            while url:
                with request(url) as response:
                    page = json.load(response)
                    link = response.headers.get('Link', '')
                if not isinstance(page, list):
                    raise ValueError('Unexpected GitHub issues response')
                for issue in page:
                    if 'pull_request' in issue or issue.get('number') in seen:
                        continue
                    seen.add(issue['number'])
                    if not issue.get('title') or not (issue.get('body') or '').strip():
                        missing += 1
                        continue
                    item = {key: issue.get(key) for key in ('number', 'title', 'body', 'html_url', 'state', 'created_at', 'updated_at', 'closed_at')}
                    out.write(json.dumps(item, ensure_ascii=False) + '\n')
                    count += 1
                match = re.search(r'<([^>]+)>;\s*rel="next"', link)
                url = match.group(1) if match else None
                print(f'[CHECK] {sid} | {count} open issue bodies fetched', flush=True)
        result = validate(staged, spec)
        digest = sha256_file(staged)
        latest = read_json(latest_path, {'files': {}})
        old = latest['files'].get(fid, {})
        old_file = root / old.get('snapshot', '') / staged.name
        if old.get('file_sha256') == digest and old_file.is_file() and sha256_file(old_file) == digest:
            return log(run, task, 'SKIPPED_UNCHANGED', 'ingestion', f'{count} issues unchanged')
        relative = Path('snapshots') / fid / digest
        dest = root / relative
        manifest = {'schema_version': '1.0', 'run_id': run, 'source_id': sid, 'repository': source['repository'], 'source_file': fp, 'source_type': 'github_issues', 'source_query': 'state=open', 'file_sha256': digest, 'validation': result, 'issues_without_body_excluded': missing, 'published_at': now(), 'status': 'published', 'license': source.get('license', 'unknown'), 'note': source.get('note')}
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if sha256_file(dest / staged.name) != digest or not (dest / 'manifest.json').exists():
                raise ValueError('Existing snapshot is incomplete or corrupted')
        else:
            temp = Path(tempfile.mkdtemp(prefix='.publish-', dir=dest.parent))
            shutil.copy2(staged, temp / staged.name)
            write_json(temp / 'manifest.json', manifest)
            os.rename(temp, dest)
        latest['files'][fid] = {'source_file': fp, 'snapshot': str(relative), 'file_sha256': digest}
        write_json(latest_path, latest)
        return log(run, task, 'PUBLISHED', 'ingestion', f'{count} open issues, {missing} without body excluded')
    except Exception as e:
        return log(run, task, 'FAILED', 'ingestion', type(e).__name__ + ': ' + str(e))


def ingest(source, spec, run, dry=False):
    sid, fp = source['source_id'], spec['path']
    if source.get('type') == 'github_issues':
        return ingest_issues(source, spec, run, dry)
    fid = file_id(fp)
    task = {'task_id': uuid.uuid4().hex, 'source_id': sid, 'file_path': fp, 'attempt': 1}
    root = DATA / 'raw' / sid
    latest_path = root / 'latest.json'
    latest = read_json(latest_path, {'files': {}})
    old = latest['files'].get(fid, {})
    try:
        commit, blob = revision(source, spec)
        old_file = root / old.get('snapshot', '') / Path(fp).name
        if old.get('blob_sha') == blob and old_file.is_file() and sha256_file(old_file) == old.get('file_sha256'):
            status, message = 'SKIPPED_UNCHANGED', 'File revision unchanged'
        elif dry:
            status, message = 'PENDING', 'Would download and validate'
        else:
            stage = DATA / 'staging' / run / sid / fid
            stage.mkdir(parents=True, exist_ok=True)
            staged = stage / Path(fp).name
            url = f'https://raw.githubusercontent.com/{source["repository"]}/{commit}/{quote(fp, safe="/")}'
            with request(url) as response, staged.open('wb') as out:
                size = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError('File exceeds 100 MiB limit')
                    out.write(chunk)
            if not staged.stat().st_size:
                raise ValueError('Downloaded file is empty')
            digest = sha256_file(staged)
            if digest == old.get('file_sha256') and old_file.is_file() and sha256_file(old_file) == digest:
                old.update({'commit_sha': commit, 'blob_sha': blob})
                write_json(latest_path, latest)
                status, message = 'SKIPPED_UNCHANGED', 'File content unchanged'
            else:
                try:
                    result = validate(staged, spec)
                except (ValueError, UnicodeError, csv.Error, json.JSONDecodeError) as e:
                    quarantine = DATA / 'quarantine' / run / sid / fid
                    quarantine.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(staged, quarantine / staged.name)
                    return log(run, task, 'QUARANTINED', 'validation', str(e))
                relative = Path('snapshots') / fid / digest
                dest = root / relative
                manifest = {'schema_version': '1.0', 'run_id': run, 'source_id': sid, 'repository': source['repository'], 'source_file': fp, 'commit_sha': commit, 'blob_sha': blob, 'file_sha256': digest, 'validation': result, 'published_at': now(), 'status': 'published', 'license': source.get('license', 'unknown'), 'note': source.get('note')}
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    if sha256_file(dest / staged.name) != digest or not (dest / 'manifest.json').exists():
                        raise ValueError('Existing snapshot is incomplete or corrupted')
                else:
                    temp = Path(tempfile.mkdtemp(prefix='.publish-', dir=dest.parent))
                    shutil.copy2(staged, temp / staged.name)
                    write_json(temp / 'manifest.json', manifest)
                    os.rename(temp, dest)
                latest['files'][fid] = {'source_file': fp, 'snapshot': str(relative), 'file_sha256': digest, 'commit_sha': commit, 'blob_sha': blob}
                write_json(latest_path, latest)
                status, message = 'PUBLISHED', f'{result["record_count"]} records'
    except Exception as e:
        status, message = 'FAILED', ('source_missing' if isinstance(e, HTTPError) and e.code == 404 else type(e).__name__) + ': ' + str(e)
    if dry:
        print(f'[{status}] {sid} | {fp} | {message}')
        return {'status': status, **task, 'message': message}
    return log(run, task, status, 'ingestion', message)


def normalized(text):
    return ' '.join(unicodedata.normalize('NFKC', str(text or '')).casefold().split())


def clean_url(value):
    try:
        p = urlsplit(value.strip())
        if p.scheme not in ('http', 'https') or not p.hostname:
            return ''
        query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')])
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), query, ''))
    except ValueError:
        return ''


def report(sources, summary=None):
    from src.classification.rules import classify
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    taxonomy = yaml.safe_load((ROOT / 'configs/role_taxonomy.yaml').read_text(encoding='utf-8'))
    unique = {}
    url_groups = {}
    raw_count = 0
    source_counts = {}
    snapshots = []
    for source in sources:
        sid = source['source_id']
        root = DATA / 'raw' / sid
        latest = read_json(root / 'latest.json', {'files': {}})
        specs = {item['path']: item for item in source['files']}
        for entry in latest['files'].values():
            spec = specs.get(entry['source_file'])
            if not spec:
                continue
            path = root / entry['snapshot'] / Path(entry['source_file']).name
            if sha256_file(path) != entry['file_sha256']:
                raise ValueError('Snapshot checksum mismatch: ' + str(path))
            snapshots.append({'source_id': sid, **entry})
            for row in rows(path, spec):
                raw_count += 1
                source_counts[sid] = source_counts.get(sid, 0) + 1
                title = str(row.get(spec['title']) or '').strip()
                desc = str(row.get(spec['description']) or '').strip()
                company = str(row.get(spec.get('company', '')) or '').strip()
                url = clean_url(str(row.get(spec.get('url', '')) or ''))
                content = hashlib.sha256('\0'.join(map(normalized, (title, company, desc))).encode()).hexdigest()
                key = 'content:' + content
                if url:
                    compatible = next((k for k in url_groups.get(url, []) if normalized(unique[k]['title']) == normalized(title) and (not company or not unique[k]['company'] or normalized(unique[k]['company']) == normalized(company))), None)
                    key = compatible or ('url:' + url + ':' + content)
                    url_groups.setdefault(url, []).append(key)
                if key not in unique:
                    unique[key] = {'title': title, 'description': desc, 'company': company, 'sources': set()}
                unique[key]['sources'].add(sid)
                if len(desc) > len(unique[key]['description']):
                    unique[key].update(title=title, description=desc, company=company)
    if not snapshots:
        raise ValueError('No published snapshots available for reporting')
    counts = {(family, role): 0 for family, roles in taxonomy.items() for role in roles}
    origins = {key: set() for key in counts}
    unknown = review = 0
    for row in unique.values():
        status, family, role = classify(row['title'], taxonomy)
        if status == 'classified':
            counts[(family, role)] += 1
            origins[(family, role)].update(row['sources'])
        elif status == 'needs_review':
            review += 1
        else:
            unknown += 1
    out = DATA / 'reports'
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'jd_coverage_by_role.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['role_family', 'primary_role', 'jd_count', 'source_count', 'unclassified_count'])
        for (family, role), n in counts.items():
            writer.writerow([family, role, n, len(origins[(family, role)]), 0])
        writer.writerow(['unclassified', 'unknown', unknown, '', unknown])
        writer.writerow(['unclassified', 'needs_review', review, '', review])
    stamp = now()
    families = list(taxonomy)
    totals = [sum(counts[(family, role)] for role in taxonomy[family]) for family in families]
    fig, ax = plt.subplots(figsize=(11, 6))
    bars = ax.bar(families + ['unknown', 'needs_review'], totals + [unknown, review], color='#3d6f98')
    ax.bar_label(bars, padding=3)
    ax.set_ylabel('Unique JD')
    ax.set_title(f'Role family distribution | n={len(unique)} | {stamp[:10]}')
    ax.tick_params(axis='x', rotation=20)
    fig.tight_layout()
    fig.savefig(out / 'role_family_distribution.png', dpi=200)
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    for ax, family in zip(axes.flat, families):
        roles = list(taxonomy[family])
        bars = ax.bar(roles, [counts[(family, role)] for role in roles], color='#3d6f98')
        ax.bar_label(bars, padding=3)
        ax.set_title(family)
        ax.tick_params(axis='x', rotation=25)
    fig.suptitle(f'Unique JD by role | n={len(unique)} | unknown={unknown}, review={review} | {stamp[:10]}')
    fig.tight_layout()
    fig.savefig(out / 'role_distribution_4panels.png', dpi=200)
    plt.close(fig)
    result = {'generated_at': stamp, 'raw_records': raw_count, 'unique_jd': len(unique), 'description_nonempty_unique': sum(bool(x['description']) for x in unique.values()), 'unknown': unknown, 'needs_review': review, 'source_raw_counts': source_counts, 'snapshots': snapshots, 'tasks': summary or [], 'method': 'Exact normalized URL with title/company compatibility; otherwise exact title/company/description. Alias role labels are preliminary.'}
    write_json(out / 'ingestion_summary.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['update', 'report'], required=True)
    parser.add_argument('--source')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    sources = registry()
    if args.source and args.source not in {s['source_id'] for s in sources}:
        parser.error('Unknown source')
    if args.mode == 'report' and (args.source or args.dry_run):
        parser.error('report does not accept --source or --dry-run')
    run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    if args.dry_run:
        results = [ingest(s, f, run, True) for s in sources if s.get('enabled') and (not args.source or s['source_id'] == args.source) for f in s['files']]
        return int(any(r['status'] == 'FAILED' for r in results))
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / '.m01.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another M01 run holds the lock')
            return 2
        if args.mode == 'report':
            print(json.dumps(report(sources), ensure_ascii=False, indent=2))
            return 0
        results = [ingest(s, f, run) for s in sources if s.get('enabled') and (not args.source or s['source_id'] == args.source) for f in s['files']]
        write_json(DATA / 'manifests/runs' / (run + '.json'), {'run_id': run, 'tasks': results})
        try:
            totals = report(sources, results)
            print(f'Raw: {totals["raw_records"]}; unique: {totals["unique_jd"]}')
        except Exception as e:
            print('Report failed:', e)
            return 1
        return int(any(r['status'] in ('FAILED', 'QUARANTINED') for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
