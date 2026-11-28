"""Merge a new sanitized eligible-JD batch into the shared CSV."""
from __future__ import annotations

import argparse
import csv
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from src.preparation.export_csv import FIELDS, _text
from src.preparation.identity import norm_url, topcv_posting_id
from src.preparation.public_export import EMAIL, PHONE


def _key(row: dict[str, str]) -> tuple[str, ...]:
    url = row['source_url']
    posting = topcv_posting_id(url)
    if posting:
        return 'topcv_posting', posting
    normalized = norm_url(url)
    if normalized:
        parts = urlsplit(normalized)
        host = (parts.hostname or '').removeprefix('www.')
        return 'url', host, parts.path.rstrip('/'), parts.query
    return 'jd_id', row['jd_id']


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    csv.field_size_limit(10_000_000)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError(f'Unexpected CSV schema: {path}')
        rows = list(reader)
    for row in rows:
        if row['eligibility_status'] != 'eligible' or not row['jd_id'] or not row['jd_text'].strip():
            raise ValueError(f'Invalid eligible JD in {path}')
        for field in ('duties', 'requirements', 'benefits', 'jd_text'):
            if EMAIL.search(row[field]) or PHONE.search(row[field]):
                raise ValueError(f'Unsanitized contact detail in {path}')
        if row['jd_text'] != _text(row):
            raise ValueError(f'JD text differs from sanitized fields in {path}')
    return rows


def _quality(row: dict[str, str]) -> tuple[int, int]:
    rank = {'full_jd': 3, 'partial_jd': 2, 'transformed_text': 1}
    return rank.get(row['content_status'], 0), sum(len(row[field]) for field in ('duties', 'requirements', 'benefits'))


def merge(base: Path, incoming: Path, destination: Path) -> dict[str, int]:
    """Preserve the best JD text for repeated URLs; never change input on error."""
    old_rows = _read(base)
    new_rows = _read(incoming)
    by_key: dict[tuple[str, ...], dict[str, str]] = {}
    for row in [*old_rows, *new_rows]:
        key = _key(row)
        prior = by_key.get(key)
        if prior is None or _quality(row) >= _quality(prior):
            by_key[key] = row
    rows = list(by_key.values())
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8-sig', newline='',
                                         dir=destination.parent, prefix='.eligible_jds-',
                                         suffix='.csv', delete=False) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {'existing': len(old_rows), 'incoming': len(new_rows),
            'total': len(rows), 'duplicates_skipped': len(old_rows) + len(new_rows) - len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--incoming', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(merge(args.base, args.incoming, args.out))


if __name__ == '__main__':
    main()
