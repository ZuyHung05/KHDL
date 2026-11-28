"""Single offline preparation pipeline for imported and newly crawled JDs."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from src.preparation.identity import norm_url, topcv_posting_id

START = {'Mô tả công việc', 'Job Description'}
REQUIRE = {'Yêu cầu ứng viên', 'Candidate Requirements'}
END = {'Quyền lợi ứng viên', 'Quyền lợi', 'Benefits', 'Địa điểm và thời gian', 'Việc làm liên quan'}
BADGE = re.compile(r'^(?:(?:PHẢN HỒI (?:VƯỢT TRỘI|THƯỜNG XUYÊN)|Nổi bật|GẤP|PROS?|HOT|TOP)\s+)+', re.I)
OUTSIDE = re.compile(r'\b(?:sales|kinh doanh|kế toán|accountant|giảng viên|giáo viên|teacher|marketing|nhân sự|human resources|hr executive)\b', re.I)
IT_STRONG = re.compile(r'\b(?:backend|frontend|fullstack|full.stack|software|developer|devops|devsecops|sre|site reliability|cloud|data engineer|data scientist|data analyst|ai engineer|machine learning|cybersecurity|cyber[ -]security|cyber threat|soc analyst|security researcher|appsec|pentest|security engineer|security architect|security analyst|information security|network security|network\s*(?:&|and)\s*security|sap|erp|oracle ebs|it support|helpdesk|ui.?ux|ux.?ui|ui designer|ux designer|business analyst|qa engineer|qc engineer|software tester|manual tester|automation tester|it manager|network engineer|system engineer|system admin|system administrator|server operation|infrastructure engineer|embedded|firmware|database administrator|db administrator|brse|agentic ai|senior java|junior java)\b|lập trình viên|lập trình|kỹ sư phần mềm|kiểm thử phần mềm|kiem thu phan mem|phân tích nghiệp vụ|khoa học dữ liệu|kỹ sư dữ liệu|an toàn thông tin|kỹ thuật it|quản trị hệ thống|hệ thống nhúng|phần cứng nhúng|bảo mật', re.I)
TECH = re.compile(r'\b(?:software|phần mềm|ứng dụng|application|code|lập trình|sap|erp|api|sql|python|java|c#|\.net|aws|azure|docker|kubernetes|figma|wireframe|firmware|linux|network|cybersecurity)\b', re.I)
PRODUCTION = re.compile(r'\b(?:cnc|máy tiện|máy phay|gia công|chất lượng sản xuất)\b', re.I)
VN = re.compile(r'việt nam|viêt nam|viet\s?nam|vietnã|\bvn\b|hà nội|ha noi|hanoi|hồ chí minh|ho chi minh|\bhcmc?\b|sài gòn|saigon|đà nẵng|da nang|đà lạt|hải phòng|haiphong|bắc ninh|bắc giang|bình dương|cần thơ|đồng nai|thái nguyên|hưng yên|hải dương|phú thọ|ninh bình|thanh hóa|thanh hoá|nghệ an|hà tĩnh|quảng ninh|quảng trị|quang ngai|quảng ngãi|quang nam|quảng nam|long an|vũng tàu|bà rịa|br-vt|biên hòa|hà nam|ha nam|khánh hòa|khánh hoà|khanh hoa|lâm đồng|đồng tháp|binh dinh|bình định|nha trang|tây ninh|thừa thiên huế', re.I)
FOREIGN = re.compile(r'\b(?:singapore|thailand|bangkok|philippines|japan|finland|malaysia|nhật bản)\b', re.I)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def restore_topcv(text: str) -> tuple[str, str, str, str]:
    """Return duties, requirements, benefits, reason; ambiguous layout is quarantined."""
    if not text:
        return '', '', '', 'missing_description'
    lines = text.splitlines()
    headings = [(i, x.strip()) for i, x in enumerate(lines) if x.strip() in START | REQUIRE | END]
    candidates = []
    for k, (i, name) in enumerate(headings):
        if name not in START:
            continue
        next_headings = headings[k + 1:]
        req = next(((j, n) for j, n in next_headings if n in REQUIRE), None)
        if not req or req[0] - i > 150:
            continue
        end = next(((j, n) for j, n in next_headings if j > req[0] and n in END), None)
        if not end or end[0] - req[0] > 150:
            continue
        duties = '\n'.join(lines[i + 1:req[0]]).strip()
        requirements = '\n'.join(lines[req[0] + 1:end[0]]).strip()
        after = next((j for j, _ in next_headings if j > end[0]), len(lines))
        benefits = '\n'.join(lines[end[0] + 1:after]).strip() if end[1] in {'Quyền lợi ứng viên', 'Quyền lợi', 'Benefits'} else ''
        if len(duties) >= 80 and len(requirements) >= 40 and 'Việc làm liên quan' not in duties + requirements:
            candidates.append((duties, requirements, benefits))
    if len(candidates) != 1:
        return '', '', '', 'ambiguous_sections' if candidates else 'sections_not_found'
    return *candidates[0], 'restored'


def classify(row: dict) -> dict:
    title = BADGE.sub('', row['title'] or '').strip()
    duties, requirements, benefits = row['duties'], row['requirements'], row['benefits']
    source = row['source_id']
    title_it = bool(IT_STRONG.search(title))
    title_non = bool(OUTSIDE.search(title))
    context_technical = bool(TECH.search((duties + '\n' + requirements)[:6000]))
    qa_ambiguous = bool(re.search(r'\b(?:qa|qc|quality assurance|quality control)\b',title,re.I)) and not bool(re.search(r'\b(?:software|phần mềm|automation|manual tester|test engineer)\b',title,re.I))
    digital_product_designer = (source in {'topcv', 'itviec'}
                                and bool(re.search(r'product design(?:er)?', title, re.I))
                                and bool(re.search(r'ui[ /-]?ux|ux[ /-]?ui|figma|wireframe', duties+'\n'+requirements, re.I)))
    erp_dev_context = (bool(re.search(r'\b(?:\.net|software|developer|dev)\b', title, re.I))
                       and bool(re.search(r'\berp\b', title, re.I))
                       and not bool(re.search(r'\b(?:sales|kinh doanh|accountant)\b', title, re.I)))
    if PRODUCTION.search(title) and not re.search(r'\b(?:software|phần mềm|it|data)\b', title, re.I):
        domain, domain_reason = 'non_it', 'production_role'
    elif title_non and title_it and erp_dev_context:
        domain, domain_reason = 'it', 'erp_developer_context'
    elif title_non and title_it:
        domain, domain_reason = 'unknown', 'title_conflict'
    elif title_non:
        domain, domain_reason = 'non_it', 'outside_it_title'
    elif qa_ambiguous and not context_technical:
        domain, domain_reason = 'unknown', 'qa_context_missing'
    elif title_it or digital_product_designer:
        domain, domain_reason = 'it', 'it_title'
    elif source != 'topcv' and row.get('old_domain') == 'it':
        domain, domain_reason = 'it', 'imported_it_evidence'
    elif re.search(r'\b(?:qa|qc|ba|it)\b', title, re.I) and context_technical:
        domain, domain_reason = 'it', 'technical_context'
    else:
        domain, domain_reason = 'unknown', 'domain_unresolved'
    loc = row['location'] or ''
    if source in {'topcv', 'itviec'}:
        location = loc.replace('(mới)', '').strip()
        vietnam = bool(VN.search(location)); foreign = bool(FOREIGN.search(location))
    else:
        vietnam = row['old_geography'] == 'vietnam'; foreign = row['old_geography'] == 'outside_vietnam'
        if not vietnam and not foreign and loc:
            vietnam = bool(VN.search(loc)); foreign = bool(FOREIGN.search(loc))
        # The local source registry identifies this dataset as Singapore
        # government vacancies. The country is inferred from source scope,
        # never presented as an explicit per-posting location.
        if source == 'careersgovsg' and not vietnam:
            foreign = True
    geography = 'unknown' if vietnam == foreign else 'vietnam' if vietnam else 'outside_vietnam'
    if source in {'topcv', 'itviec'}:
        content = ('full_jd' if row['parse_status'] in {'restored', 'structured'}
                   else 'partial_jd' if row['parse_status'] == 'partial' else 'unverified')
    else:
        content = row['old_content']
    analyzable = content in {'full_jd', 'partial_jd', 'transformed_text'}
    if domain == 'non_it' or geography == 'outside_vietnam':
        status = 'not_eligible'
    elif domain == 'it' and geography == 'vietnam' and analyzable:
        status = 'eligible'
    else:
        status = 'needs_review'
    reasons = [domain_reason]
    if geography == 'unknown': reasons.append('geography_unresolved')
    if content != 'full_jd': reasons.append('content_' + (row['parse_status'] if source in {'topcv', 'itviec'} else content))
    if source == 'careersgovsg' and geography == 'outside_vietnam' and row['old_geography'] == 'unknown':
        reasons.append('country_inferred_from_source_registry')
    return {**row, 'title': title, 'domain_status': domain, 'geography_status': geography,
            'content_status': content, 'eligibility_status': status, 'review_reasons': reasons,
            'content_quality_caveat': content if content in {'partial_jd','transformed_text'} else '',
            'evidence': json.dumps({'title': title, 'location': loc, 'parse_status': row['parse_status'],
                                    'country_basis': ('source_registry_singapore' if source == 'careersgovsg' and row['old_geography'] == 'unknown'
                                                      else 'explicit_location_fallback' if source not in {'topcv','itviec'} and row['old_geography'] == 'unknown' and geography != 'unknown'
                                                      else 'record'),
                                    'duties_excerpt': duties[:200], 'requirements_excerpt': requirements[:200]}, ensure_ascii=False)}


def load_inputs(paths: tuple[Path, ...]) -> list[dict]:
    """Read canonical imported Parquet and crawler JSONL; no legacy stages needed."""
    rows = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.suffix == '.parquet':
            imported = pq.read_table(path).to_pylist()
            required = {'record_id', 'source_id', 'title', 'duties', 'requirements', 'parse_status'}
            if imported and not required.issubset(imported[0]):
                raise ValueError(f'Unsupported imported Parquet schema: {path}')
            for record in imported:
                rows.append({
                    'record_id': record['record_id'], 'source_id': record['source_id'],
                    'source_url': record.get('source_url') or '', 'title': record.get('title') or '',
                    'company': record.get('company') or '', 'location': record.get('location') or '',
                    'duties': record.get('duties') or '', 'requirements': record.get('requirements') or '',
                    'benefits': record.get('benefits') or '', 'parse_status': record['parse_status'],
                    'old_geography': record.get('old_geography') or record.get('geography_status'),
                    'old_domain': record.get('old_domain') or record.get('domain_status'),
                    'old_content': record.get('old_content') or record.get('content_status'),
                    'old_eligibility': record.get('eligibility_status'),
                    'member_count': record.get('member_count') or 1,
                })
        elif path.suffix == '.jsonl':
            with path.open(encoding='utf-8') as stream:
                for number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    site = record.get('site') or 'topcv'
                    url = norm_url(record.get('job_url') or '')
                    host = urlsplit(url).hostname if url else None
                    allowed_hosts = {'topcv': {'topcv.vn', 'www.topcv.vn'},
                                     'itviec': {'itviec.com', 'www.itviec.com'}}
                    if site not in allowed_hosts or host not in allowed_hosts[site]:
                        raise ValueError(f'Unsupported crawler row at {path}:{number}')
                    if record.get('duties') or record.get('requirements'):
                        duties, req, benefits, parse_status = (
                            record.get('duties') or '', record.get('requirements') or '',
                            record.get('benefits') or '', record.get('parse_status') or 'partial')
                    elif site == 'topcv':
                        duties, req, benefits, parse_status = restore_topcv(record.get('description') or '')
                    else:
                        duties, req, benefits, parse_status = '', '', '', 'missing_description'
                    rows.append({
                        'record_id': 'crawl:' + site + ':' + hashlib.sha256(
                            f'{path.resolve()}:{number}:{record["job_url"]}'.encode()).hexdigest(),
                        'source_id': site, 'source_url': record['job_url'],
                        'title': record.get('title') or '', 'company': record.get('company') or '',
                        'location': record.get('location') or '', 'duties': duties,
                        'requirements': req, 'benefits': benefits, 'parse_status': parse_status,
                        'old_geography': None, 'old_domain': None, 'old_content': None,
                        'old_eligibility': None, 'member_count': 1,
                    })
        else:
            raise ValueError(f'Unsupported input type: {path}')
    return rows


def run(root: Path, run_id: str, *, execute: bool = False,
        inputs: tuple[Path, ...] = (), output_dir: Path | None = None):
    from .taxonomy import enrich
    root = Path(root)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id): raise ValueError('Invalid run ID')
    paths = tuple(Path(path).resolve() for path in inputs)
    if not paths:
        raise ValueError('At least one --input Parquet or JSONL is required')
    rows = load_inputs(paths)
    if not rows:
        raise ValueError('Input files contain no JD records')
    fingerprints = {'sources': {str(path): sha(path) for path in paths},
                    'rules': sha(Path(__file__)),
                    'identity_rules': sha(Path(__file__).with_name('identity.py')),
                    'hierarchy_rules': sha(Path(__file__).with_name('taxonomy.py')),
                    'role_patterns': sha(Path(__file__).with_name('role_report.py')),
                    'export_rules': sha(Path(__file__).with_name('export_csv.py')),
                    'report_rules': sha(Path(__file__).with_name('report.py'))}
    dest = Path(output_dir) if output_dir else root / 'data/curated/preparation' / run_id
    if not execute:
        print(json.dumps({'run_id': run_id, 'input_records': len(rows),
                          'inputs': fingerprints}, ensure_ascii=False, indent=2)); return
    if dest.exists():
        manifest = json.loads((dest / 'manifest.json').read_text())
        if manifest['inputs'] != fingerprints: raise ValueError('Existing run ID uses different inputs; choose another --run-id')
        print(json.dumps({'status': 'CACHED', 'run': str(dest), 'counts': manifest['counts']}, ensure_ascii=False)); return
    rows = [classify(r) for r in rows]
    # Conservative cross-source identity; review content similarities separately.
    keys = defaultdict(list)
    for i, r in enumerate(rows):
        if r['source_url']:
            u = norm_url(r['source_url'])
            if u: keys[('url', u)].append(i)
            post = topcv_posting_id(r['source_url'])
            if post: keys[('topcv', post)].append(i)
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for indices in keys.values():
        for i in indices[1:]:
            j = indices[0]
            same_url = rows[i]['source_url'] and norm_url(rows[i]['source_url']) == norm_url(rows[j]['source_url'])
            if (same_url or (rows[i]['title'].casefold() == rows[j]['title'].casefold()
                and rows[i]['company'].casefold() == rows[j]['company'].casefold()
                and rows[i]['location'].casefold() == rows[j]['location'].casefold())): parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(len(rows)): groups[find(i)].append(i)
    reps, mappings = [], []
    for indices in groups.values():
        representative = max(indices, key=lambda i:(rows[i]['parse_status'] in ('restored', 'original_source'),bool(rows[i]['requirements']),len(rows[i]['duties'])))
        rep = enrich(dict(rows[representative])); rep['group_members'] = [rows[i]['record_id'] for i in indices]
        rep['member_count'] = sum(rows[i]['member_count'] for i in indices)
        reps.append(rep)
        for i in indices: mappings.append({'record_id': rows[i]['record_id'], 'representative_record_id': rep['record_id'], 'source_id': rows[i]['source_id']})
    dest.mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist(reps), dest / 'master_jds.parquet', compression='snappy')
    pq.write_table(pa.Table.from_pylist(mappings), dest / 'duplicate_mapping.parquet', compression='snappy')
    from .export_csv import export
    export(dest/'master_jds.parquet', dest, run_id)
    from .role_report import run as role_report
    role_report(dest/'master_jds.parquet', dest)
    for status in ('eligible', 'needs_review', 'not_eligible'):
        with (dest / (status + '.csv')).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['record_id','source_id','source_url','title','location','domain_status','geography_status','content_status','content_quality_caveat','parse_status','role_family','primary_role','role_confidence','skill_count','review_reasons'])
            writer.writeheader()
            for row in reps:
                if row['eligibility_status'] == status:
                    writer.writerow({k: '; '.join(row[k]) if k == 'review_reasons' else row.get(k) for k in writer.fieldnames})
    # Fixed, stratified sample for independent inspection; no automatic gold label.
    strata = defaultdict(list)
    for row in reps:
        strata[(row['source_id'], row['eligibility_status'])].append(row)
    for values in strata.values():
        values.sort(key=lambda r: hashlib.sha256(('audit-current:' + r['record_id']).encode()).hexdigest())
    sample = []
    while len(sample) < min(150, len(reps)) and any(strata.values()):
        for key in sorted(strata):
            if strata[key] and len(sample) < 150: sample.append(strata[key].pop(0))
    with (dest/'audit_150.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['split','record_id','source_id','title','source_url','eligibility_status','review_reasons','role_family','primary_role','role_confidence','role_evidence','skill_count','human_label','human_notes'])
        writer.writeheader()
        for i,row in enumerate(sample):
            writer.writerow({'split':'dev' if i%2==0 else 'holdout','record_id':row['record_id'],
                             'source_id':row['source_id'],'title':row['title'],'source_url':row['source_url'],
                             'eligibility_status':row['eligibility_status'],'review_reasons':'; '.join(row['review_reasons']),
                             'role_family':row['role_family'],'primary_role':row['primary_role'],
                             'role_confidence':row['role_confidence'],'role_evidence':row['role_evidence'],
                             'skill_count':row['skill_count'],
                             'human_label':'','human_notes':''})
    counts = dict(Counter(r['eligibility_status'] for r in reps))
    by_source = {s:dict(Counter(r['eligibility_status'] for r in reps if r['source_id']==s)) for s in sorted({r['source_id'] for r in reps})}
    review = dict(Counter(reason for r in reps if r['eligibility_status']=='needs_review' for reason in r['review_reasons']))
    transitions = dict(Counter((r['old_eligibility'] or 'new') + ' -> ' + r['eligibility_status'] for r in reps))
    summary = {'input_groups': len(rows), 'input_raw_records_represented': sum(r['member_count'] for r in rows),
               'output_groups': len(reps), 'counts': counts, 'by_source': by_source, 'review_reasons': review,
               'transitions': transitions, 'topcv_parse': dict(Counter(r['parse_status'] for r in rows if r['source_id']=='topcv')),
               'eligible_role_confidence': dict(Counter(r['role_confidence'] for r in reps if r['eligibility_status']=='eligible'))}
    (dest / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    from .report import render
    render(dest, summary)
    files = {p.name:sha(p) for p in dest.iterdir() if p.is_file()}
    manifest = {'run_id': run_id, 'created_at': datetime.now(timezone.utc).isoformat(), 'inputs': fingerprints, 'files': files, 'counts': counts}
    (dest / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({'status':'COMPLETED','run':str(dest),'summary':summary},ensure_ascii=False,indent=2))
