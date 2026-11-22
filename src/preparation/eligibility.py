"""Explainable, non-destructive M02 eligibility assessment."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

VERSION = 'eligibility_v1'
IT = re.compile(r'\b(?:software|backend|back.end|frontend|front.end|full.stack|devops|cloud|data|machine learning|artificial intelligence|cybersecurity|security|systems?|network|database|web|mobile|site reliability|platform|it)\b.{0,35}\b(?:engineer|developer|architect|programmer|scientist|analyst|administrator|specialist|tester)\b|\b(?:lập trình viên|kỹ sư phần mềm|an ninh mạng|khoa học dữ liệu)\b', re.I)
NON_IT = re.compile(r'\b(?:teacher|nurse|accountant|driver|receptionist|sales executive|sales representative|marketing executive|human resources executive)\b|\b(?:giáo viên|kế toán|tài xế|điều dưỡng)\b', re.I)
DUTIES = re.compile(r'what you will be working on|responsibilit(?:y|ies)|job duties|what you.?ll do|mô tả công việc|nhiệm vụ', re.I)
QUALIFICATIONS = re.compile(r'what we are looking for|requirements|qualifications|what you.?ll need|yêu cầu(?: công việc)?', re.I)
VN_CITIES = {'Hà Nội','Hồ Chí Minh','Đà Nẵng','Hải Phòng','Bắc Ninh','Bình Dương','Cần Thơ','Đồng Nai'}
SENTINELS = {'', 'null', 'nan', 'n/a', 'na', 'none', '[]', '{}'}

def text(value):
    if value is None: return ''
    if not isinstance(value, str): return str(value)
    value = value.strip()
    return '' if value.casefold() in SENTINELS else value

def assess(row):
    evidence = {'domain': [], 'geography': [], 'content': []}
    reasons = []
    title = text(row.get('job_title_clean'))
    it, non = IT.search(title), NON_IT.search(title)
    if it and non:
        domain = 'unknown'; reasons.append('domain_conflicting_title')
    elif it:
        domain = 'it'; reasons.append('domain_it_title')
    elif non:
        domain = 'non_it'; reasons.append('domain_non_it_title')
    else:
        domain = 'unknown'; reasons.append('domain_no_clear_evidence')
    for match, rule in ((it, 'it_title'), (non, 'non_it_title')):
        if match: evidence['domain'].append({'field':'job_title_clean','value':match.group(), 'rule':rule})
    regions = set()
    for field in ('country_normalized', 'location_normalized'):
        for value in row.get(field) or []:
            region = 'vietnam' if value == 'Vietnam' or value in VN_CITIES else 'outside_vietnam' if value in {'Singapore','Thailand'} else None
            if region:
                regions.add(region); evidence['geography'].append({'field':field,'value':value,'rule':'explicit_normalized_geography'})
    flags = row.get('normalization_flags') or []
    if len(regions) > 1 or any('location_conflict' in f or 'country_conflict' in f for f in flags):
        geography = 'unknown'; reasons.append('geography_conflict')
    elif regions:
        geography = next(iter(regions)); reasons.append('geography_explicit_' + geography)
    else:
        geography = 'unknown'; reasons.append('geography_no_clear_evidence')
    fields = {name: text(row.get(name)) for name in ('description_clean','requirements_clean','responsibilities_clean','raw_job_text_clean','description_transformed_clean')}
    issue = row.get('source_id') == 'awesome_jobs_vietnam'
    if issue and any(fields.values()):
        content = 'issue_unstructured'; why = 'github_issue_not_assumed_single_position'
    elif not any(fields[k] for k in ('description_clean','requirements_clean','responsibilities_clean','raw_job_text_clean')) and fields['description_transformed_clean']:
        content = 'transformed_text'; why = 'transformed_only'
    else:
        desc, req, duties, raw = (fields[k] for k in ('description_clean','requirements_clean','responsibilities_clean','raw_job_text_clean'))
        combined = '\n'.join((desc,raw))
        if ((len(desc) >= 100 or len(duties) >= 100) and len(req) >= 40) or (len(combined) >= 200 and DUTIES.search(combined) and QUALIFICATIONS.search(combined)):
            content = 'full_jd'; why = 'substantive_duties_and_requirements'
        elif any((desc,req,duties,raw)):
            content = 'partial_jd'; why = 'partial_content'
        else:
            content = 'insufficient'; why = 'no_job_content'
    reasons.append('content_' + why)
    for field, value in fields.items():
        if value: evidence['content'].append({'field':field,'characters':len(value),'rule':why})
    if domain == 'non_it' or geography == 'outside_vietnam' or content == 'insufficient':
        eligibility = 'not_eligible'; reasons.append('eligibility_clear_mismatch')
    elif domain == 'it' and geography == 'vietnam' and content == 'full_jd':
        eligibility = 'eligible'; reasons.append('eligibility_all_criteria_met')
    else:
        eligibility = 'needs_review'; reasons.append('eligibility_missing_or_incomplete_evidence')
    return domain, geography, content, eligibility, reasons, json.dumps(evidence, ensure_ascii=False, sort_keys=True)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def run(root):
    root = Path(root); staging = root/'data/staging'; reports = root/'data/reports'
    input_path = staging/'normalized_jds.parquet'; mapping_path = staging/'duplicate_mapping.parquet'
    previous = json.loads((reports/'normalization_report.json').read_text())
    if sha(input_path) != previous['output_sha256'] or sha(mapping_path) != previous['mapping_sha256']:
        raise ValueError('Input or mapping checksum does not match normalization report')
    table = pq.read_table(input_path); mappings = pq.read_table(mapping_path).to_pylist(); rows = table.to_pylist()
    ids = [r['record_id'] for r in mappings]; rep_ids = [r['record_id'] for r in rows]
    if len(set(ids)) != len(ids) or len(set(rep_ids)) != len(rep_ids): raise ValueError('Duplicate provenance IDs')
    counts = Counter(m['representative_record_id'] for m in mappings)
    if set(counts) != set(rep_ids) or any(counts[r['record_id']] != r['member_count'] for r in rows): raise ValueError('Provenance mapping mismatch')
    representatives = {r['record_id']: r for r in rows}
    if any(m['jd_id'] != representatives[m['representative_record_id']]['jd_id'] for m in mappings): raise ValueError('Mapping jd_id mismatch')
    members = {r['record_id']: {m['record_id'] for m in json.loads(r['members_json'])} for r in rows}
    if any(m['record_id'] not in members[m['representative_record_id']] for m in mappings): raise ValueError('Mapping member mismatch')
    by = defaultdict(lambda: defaultdict(Counter)); total = defaultdict(Counter); values = [[] for _ in range(6)]
    names = ('domain_status','geography_status','content_status','eligibility_status','eligibility_reason_codes','eligibility_evidence')
    for row in rows:
        result = assess(row)
        for i, v in enumerate(result): values[i].append(v)
        for name, val in zip(names[:4], result[:4]): by[row['source_id']][name][val] += 1; total[name][val] += 1
    types = [pa.string()]*4 + [pa.list_(pa.string()),pa.string()]
    for name, val, typ in zip(names, values, types): table = table.append_column(name, pa.array(val, type=typ))
    meta = dict(table.schema.metadata or {}); meta.update({b'eligibility_version':VERSION.encode(),b'eligibility_input_sha256':sha(input_path).encode(),b'eligibility_rules_sha256':sha(Path(__file__)).encode()})
    table = table.replace_schema_metadata(meta)
    output = staging/'eligible_jds.parquet'; pq.write_table(table, output)
    report = {'generated_at':datetime.now(timezone.utc).isoformat(), 'version':VERSION, 'rules_sha256':sha(Path(__file__)), 'input_sha256':sha(input_path), 'mapping_sha256':sha(mapping_path),'output_sha256':sha(output), 'input_groups':len(rows),'output_groups':table.num_rows,'mapped_raw_records':len(mappings), 'totals':total,'by_source':by}
    (reports/'eligibility_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--root',default='.')
    run(p.parse_args().root)
