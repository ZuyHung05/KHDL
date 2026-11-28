"""Publish one eligible-JD CSV with contact details removed from JD text."""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from src.preparation.export_csv import _text

EMAIL = re.compile(r'(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
PHONE = re.compile(r'(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)')
TEXT_FIELDS = ('duties', 'requirements', 'benefits')


def export_public(source: Path, destination: Path) -> dict[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    csv.field_size_limit(10_000_000)
    counts = {'rows': 0, 'emails_redacted': 0, 'phones_redacted': 0}
    seen = set()
    with source.open(encoding='utf-8-sig', newline='') as input_stream, \
            destination.open('w', encoding='utf-8-sig', newline='') as output_stream:
        reader = csv.DictReader(input_stream)
        if not reader.fieldnames or not {'jd_id', 'eligibility_status', 'jd_text', *TEXT_FIELDS}.issubset(reader.fieldnames):
            raise ValueError('Input is not a shareable JD CSV')
        writer = csv.DictWriter(output_stream, fieldnames=reader.fieldnames, lineterminator='\n')
        writer.writeheader()
        for row in reader:
            if row['eligibility_status'] != 'eligible':
                raise ValueError('Only eligible JD rows may be published')
            if not row['jd_id'] or row['jd_id'] in seen:
                raise ValueError('Missing or duplicate JD ID')
            seen.add(row['jd_id'])
            for field in TEXT_FIELDS:
                value = row[field]
                value, n_email = EMAIL.subn('[email]', value)
                value, n_phone = PHONE.subn('[số điện thoại]', value)
                counts['emails_redacted'] += n_email
                counts['phones_redacted'] += n_phone
                row[field] = value
            row['jd_text'] = _text(row)
            writer.writerow(row)
            counts['rows'] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(export_public(args.input, args.out))


if __name__ == '__main__':
    main()
