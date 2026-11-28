import csv

import pytest

from src.preparation.export_csv import FIELDS, _text
from src.preparation.merge_public_dataset import merge


def _row(jd_id, url, duties, *, quality='full_jd'):
    row = {field: '' for field in FIELDS}
    row.update(jd_id=jd_id, source_id='topcv', source_url=url,
               eligibility_status='eligible', content_status=quality,
               duties=duties, requirements='AWS')
    row['jd_text'] = _text(row)
    return row


def _write(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def _read(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def test_merge_public_dataset_deduplicates_topcv_posting_and_preserves_best_text(tmp_path):
    old = tmp_path/'old.csv'
    incoming = tmp_path/'incoming.csv'
    output = tmp_path/'out.csv'
    _write(old, [_row('old', 'https://www.topcv.vn/viec-lam/engineer/123.html',
                      'Long original description.', quality='full_jd')])
    _write(incoming, [
        _row('new-duplicate', 'https://topcv.vn/viec-lam/new-slug/123.html',
             'Short.', quality='partial_jd'),
        _row('new-unique', 'https://topcv.vn/viec-lam/other/456.html',
             'Another complete job.'),
    ])
    stats = merge(old, incoming, output)
    rows = _read(output)
    assert stats == {'existing': 1, 'incoming': 2, 'total': 2, 'duplicates_skipped': 1}
    assert [row['jd_id'] for row in rows] == ['old', 'new-unique']


def test_merge_rejects_unsanitized_batch_without_overwriting_dataset(tmp_path):
    base = tmp_path/'base.csv'
    incoming = tmp_path/'incoming.csv'
    _write(base, [_row('one', 'https://topcv.vn/viec-lam/engineer/123.html', 'Build systems.')])
    _write(incoming, [_row('two', 'https://topcv.vn/viec-lam/other/456.html',
                           'Email hr@example.com')])
    before = base.read_bytes()
    with pytest.raises(ValueError, match='Unsanitized'):
        merge(base, incoming, base)
    assert base.read_bytes() == before
