"""Create stable, shareable CSV views from a prepared JD release."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pyarrow.parquet as pq

FIELDS = [
    'release_id', 'jd_id', 'source_id', 'source_url', 'title', 'company',
    'location', 'geography_status', 'domain_status', 'eligibility_status',
    'role_family', 'primary_role', 'role_confidence', 'role_confidence_score',
    'content_status', 'content_quality_caveat', 'parse_status', 'review_reasons',
    'skills', 'duties', 'requirements', 'benefits', 'jd_text', 'member_count',
]
VIEWS = ('jds_all.csv', 'jds_eligible.csv', 'jds_eligible_labeled.csv')


def _text(row: dict) -> str:
    parts = [(label, (row.get(field) or '').strip()) for label, field in (
        ('Nhiệm vụ', 'duties'), ('Yêu cầu', 'requirements'), ('Quyền lợi', 'benefits'))]
    return '\n\n'.join(f'{label}:\n{value}' for label, value in parts if value)


def _skills(raw: str | None) -> str:
    try:
        evidence = json.loads(raw or '[]')
    except (TypeError, ValueError):
        return ''
    seen, result = set(), []
    for item in evidence if isinstance(evidence, list) else []:
        value = item.get('skill') if isinstance(item, dict) else None
        if isinstance(value, str) and value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)
    return '; '.join(result)


def _flat(row: dict, release_id: str) -> dict:
    reasons = row.get('review_reasons') or []
    if isinstance(reasons, str):
        reasons = [reasons]
    result = {key: row.get(key, '') for key in FIELDS}
    result.update({
        'release_id': release_id,
        'jd_id': row['record_id'],
        'review_reasons': '; '.join(reasons),
        'skills': _skills(row.get('skills_evidence')),
        'jd_text': _text(row),
    })
    return result


def export(master: Path, output_dir: Path, release_id: str) -> dict[str, int]:
    """Write all, eligible and known-role views with identical columns."""
    rows = sorted(pq.read_table(master).to_pylist(), key=lambda row: row['record_id'])
    output_dir.mkdir(parents=True, exist_ok=True)
    handles = {}
    writers = {}
    counts = {name: 0 for name in VIEWS}
    try:
        for name in VIEWS:
            handle = (output_dir/name).open('w', encoding='utf-8-sig', newline='')
            handles[name] = handle
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writers[name] = writer
        for row in rows:
            item = _flat(row, release_id)
            names = [VIEWS[0]]
            if row['eligibility_status'] == 'eligible':
                names.append(VIEWS[1])
                if row.get('primary_role') not in (None, '', 'unknown'):
                    names.append(VIEWS[2])
            for name in names:
                writers[name].writerow(item)
                counts[name] += 1
    finally:
        for handle in handles.values():
            handle.close()
    return counts
