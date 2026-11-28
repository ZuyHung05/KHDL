import json

import pyarrow as pa
import pyarrow.parquet as pq

from src.preparation.identity import norm_url
from src.preparation.pipeline import restore_topcv, classify, run


def item(title, duties='Develop applications in Python.', requirements='Python and SQL experience.', **extra):
    row = {'title': title, 'source_id': 'topcv', 'location': 'Hà Nội (mới)', 'duties': duties,
            'requirements': requirements, 'benefits': '', 'parse_status': 'restored',
            'old_geography': None, 'old_domain': None, 'old_content': None}
    row.update(extra)
    return row


def test_restore_uses_main_jd_not_navigation_or_related_jobs():
    raw = 'Việc làm liên quan\nMenu\nMô tả công việc\n' + 'Build API. '*12 + '\nYêu cầu ứng viên\n' + 'Python SQL. '*7 + '\nQuyền lợi ứng viên\nHealthcare\nViệc làm liên quan\nSales Engineer'
    duties, requirements, benefits, status = restore_topcv(raw)
    assert status == 'restored' and 'Build API' in duties and 'Python SQL' in requirements
    assert 'Sales Engineer' not in duties + requirements + benefits


def test_ambiguous_sections_are_not_automatically_eligible():
    raw = ('Mô tả công việc\n' + 'Build API. '*12 + '\nYêu cầu ứng viên\n' + 'Python SQL. '*7 + '\nQuyền lợi ứng viên\nBenefits\n')*2
    assert restore_topcv(raw)[-1] == 'ambiguous_sections'
    assert classify(item('Backend Developer', parse_status='ambiguous_sections'))['eligibility_status'] == 'needs_review'


def test_role_boundaries():
    assert classify(item('Fresher Backend (.NET/C#)'))['eligibility_status'] == 'eligible'
    assert classify(item('Nhân Viên Kinh Doanh Phần Mềm'))['eligibility_status'] == 'not_eligible'
    assert classify(item('Kỹ Sư Lập Trình Máy CNC'))['eligibility_status'] == 'not_eligible'
    assert classify(item('QA Engineer', duties='Check products in a factory.', requirements='Factory process.'))['eligibility_status'] == 'needs_review'


def test_unknown_location_stays_in_review():
    x = item('Backend Developer', location='Unknown & 7 nơi khác')
    assert classify(x)['eligibility_status'] == 'needs_review'


def test_partial_and_transformed_are_analyzable_with_caveat():
    for content in ('partial_jd', 'transformed_text'):
        row = item('Backend Developer', source_id='it_job_posting', old_geography='vietnam',
                   old_content=content)
        result = classify(row)
        assert result['eligibility_status'] == 'eligible'
        assert result['content_quality_caveat'] == content


def test_singapore_source_scope_is_explicitly_marked_as_inference():
    row = item('Software Engineer', source_id='careersgovsg', location='',
               old_geography='unknown', old_content='full_jd')
    result = classify(row)
    assert result['geography_status'] == 'outside_vietnam'
    assert result['eligibility_status'] == 'not_eligible'
    assert 'country_inferred_from_source_registry' in result['review_reasons']


def test_structured_itviec_description_is_eligible():
    row = item('Cloud Engineer', source_id='itviec', location='Ho Chi Minh', parse_status='structured')
    result = classify(row)
    assert result['eligibility_status'] == 'eligible'
    assert result['content_status'] == 'full_jd'


def test_observed_it_roles_and_new_vietnam_location():
    for title in ('Embedded Firmware Engineer', 'Security Architect', 'UX/UI Designer',
                  'Server Operation (System Admin, Linux)'):
        row = item(title, source_id='itviec', location='Ho Chi Minh', parse_status='structured')
        assert classify(row)['eligibility_status'] == 'eligible'
    row = item('UI/UX Designer', location='Quảng Trị', parse_status='restored')
    assert classify(row)['geography_status'] == 'vietnam'


def test_explicit_location_fallback_does_not_guess_remote():
    local = item('IT ERP Specialist', source_id='dpl_evaluation', location='Long An',
                 old_geography='unknown', old_content='partial_jd')
    assert classify(local)['eligibility_status'] == 'eligible'
    assert 'explicit_location_fallback' in classify(local)['evidence']
    remote = item('IT Support', source_id='dpl_evaluation', location='Remote',
                  old_geography='unknown', old_content='full_jd')
    assert classify(remote)['geography_status'] == 'unknown'


def test_observed_cyber_and_embedded_title_variants():
    for title in ('SOC Analyst Tier 3', 'Cyber Threat Analyst', 'Senior Site Reliability Engineer',
                  'NETWORK & SECURITY Tech Lead', 'Embedded Firmware Engineer',
                  'Kỹ Sư Phát Triển Hệ Thống Nhúng'):
        assert classify(item(title))['domain_status'] == 'it'
    assert classify(item('Product Designer', duties='Thiết kế UX/UI sản phẩm số bằng Figma.'))['domain_status'] == 'it'


def test_explicit_parquet_and_jsonl_inputs_deduplicate_tracking_urls(tmp_path):
    url = 'https://www.topcv.vn/viec-lam/cloud-engineer/123.html'
    imported = tmp_path/'import.parquet'
    pq.write_table(pa.Table.from_pylist([{
        'record_id': 'legacy:1', 'source_id': 'it_job_posting',
        'source_url': url+'?ta_source=JobSearchList', 'title': 'Cloud Engineer',
        'company': 'Example', 'location': 'Hà Nội', 'duties': 'Operate AWS cloud.',
        'requirements': 'AWS and Terraform.', 'benefits': '',
        'parse_status': 'original_source', 'old_geography': 'vietnam',
        'old_domain': 'it', 'old_content': 'transformed_text',
    }]), imported)
    jobs = tmp_path/'jobs.jsonl'
    jobs.write_text(json.dumps({'site':'topcv', 'job_url':url, 'title':'Cloud Engineer',
                                 'company':'Example', 'location':'Hà Nội',
                                 'description':'Mô tả công việc\n'+'Build cloud systems. '*8+
                                 '\nYêu cầu ứng viên\n'+'AWS Terraform. '*7+
                                 '\nQuyền lợi ứng viên\nBenefits'})+'\n')
    destination = tmp_path/'result'
    run(tmp_path, 'sample', execute=True, inputs=(imported, jobs), output_dir=destination)
    summary = json.loads((destination/'summary.json').read_text())
    assert summary['input_groups'] == 2
    assert summary['output_groups'] == 1
    assert summary['counts']['eligible'] == 1
    assert norm_url(url+'?ta_source=JobSearchList') == norm_url(url)
    manifest = json.loads((destination/'manifest.json').read_text())
    assert len(manifest['inputs']['sources']) == 2
