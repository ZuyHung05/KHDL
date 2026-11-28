import csv
import json

import pyarrow as pa
import pyarrow.parquet as pq

from src.preparation.export_csv import FIELDS, export


def test_shareable_csv_views_keep_full_text_and_separate_unknown_roles(tmp_path):
    rows = [
        {'record_id': 'a', 'source_id': 'topcv', 'source_url': 'https://example.test/a',
         'title': 'Cloud Engineer', 'eligibility_status': 'eligible',
         'role_family': 'Infrastructure & Security', 'primary_role': 'Cloud',
         'duties': 'Build cloud systems.', 'requirements': 'AWS and SQL.',
         'benefits': 'Insurance.', 'review_reasons': [],
         'skills_evidence': json.dumps([{'skill': 'AWS'}, {'skill': 'AWS'}, {'skill': 'SQL'}])},
        {'record_id': 'b', 'source_id': 'itviec', 'source_url': 'https://example.test/b',
         'title': 'Technical Specialist', 'eligibility_status': 'eligible',
         'primary_role': 'unknown', 'duties': 'Support systems.',
         'requirements': '', 'benefits': '', 'review_reasons': [], 'skills_evidence': '[]'},
        {'record_id': 'c', 'source_id': 'topcv', 'source_url': 'https://example.test/c',
         'title': 'Unknown', 'eligibility_status': 'needs_review',
         'primary_role': 'unknown', 'duties': '', 'requirements': '', 'benefits': '',
         'review_reasons': ['geography_unresolved'], 'skills_evidence': '[]'},
    ]
    master = tmp_path/'master.parquet'
    pq.write_table(pa.Table.from_pylist(rows), master)
    counts = export(master, tmp_path, 'test_run')
    assert counts == {'jds_all.csv': 3, 'jds_eligible.csv': 2,
                      'jds_eligible_labeled.csv': 1}
    with (tmp_path/'jds_eligible_labeled.csv').open(encoding='utf-8-sig', newline='') as stream:
        exported = list(csv.DictReader(stream))
    assert list(exported[0]) == FIELDS
    assert exported[0]['release_id'] == 'test_run'
    assert exported[0]['jd_id'] == 'a'
    assert exported[0]['skills'] == 'AWS; SQL'
    assert 'Nhiệm vụ:\nBuild cloud systems.' in exported[0]['jd_text']
    assert 'Yêu cầu:\nAWS and SQL.' in exported[0]['jd_text']
