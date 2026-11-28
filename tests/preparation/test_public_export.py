import csv

from src.preparation.public_export import export_public


def test_public_export_keeps_analysis_fields_and_redacts_contacts(tmp_path):
    source = tmp_path/'source.csv'
    fields = ['jd_id', 'eligibility_status', 'title', 'duties', 'requirements', 'benefits', 'jd_text']
    with source.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow({'jd_id': '1', 'eligibility_status': 'eligible', 'title': 'Cloud Engineer',
                         'duties': 'Apply via hr@example.com or 0912345678.',
                         'requirements': 'AWS.', 'benefits': '', 'jd_text': 'old text'})
    destination = tmp_path/'public.csv'
    counts = export_public(source, destination)
    with destination.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert counts == {'rows': 1, 'emails_redacted': 1, 'phones_redacted': 1}
    assert rows[0]['title'] == 'Cloud Engineer'
    assert 'hr@example.com' not in rows[0]['jd_text']
    assert '[email]' in rows[0]['duties']
    assert '[số điện thoại]' in rows[0]['jd_text']
