"""Evidence-based eligibility assessment; preserves eligibility_v1 artifacts."""
import argparse, json, re
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import pyarrow as pa
import pyarrow.parquet as pq
from src.preparation.eligibility import assess as v1_assess, sha, text

VERSION = 'eligibility_v2'
IT_TITLE = re.compile(r'\b(?:ai engineer|machine learning engineer|software engineer|software developer|software architect|programmer|devops|sre|site reliability engineer|data scientist|data engineer|data analyst|ruby on rails developer|java developer|python developer|dwh developer|bi developer|backend developer|frontend developer|full.stack developer|web developer|mobile developer|cloud engineer|cybersecurity|cyber security|penetration tester|test automation engineer|ui.?ux designer|ux designer)\b|lập trình viên|kỹ sư lập trình|kỹ sư phần mềm|an ninh mạng|bảo mật thông tin', re.I)
IT_DUTY = re.compile(r'\b(?:develop|build|design|implement|maintain|test|write|debug)\w*\s+(?:and\s+\w+\s+)?(?:software|applications?|web applications?|software products?|source code|automated tests?|apis?)\b|\b(?:phát triển|lập trình|kiểm thử)\s+(?:phần mềm|ứng dụng|hệ thống phần mềm)\b',re.I)
TECH_EDUCATION = re.compile(r'\b(?:coding|programming|software|unity|lập trình|phần mềm)\b',re.I)
AMBIGUOUS = re.compile(r'\b(?:security engineer|systems engineer|system engineer)\b', re.I)
CYBER = re.compile(r'cyber|information security|network security|penetration|an ninh mạng|an toàn thông tin|bảo mật thông tin',re.I)
GEO_LINE = re.compile(r'(?im)^\s*(?:[#*\- ]{0,8})(?:work(?:ing)? location|job location|location|địa điểm(?: làm việc)?|nơi làm việc)\s*[:：]\s*([^\n]{1,150})')
GEO = re.compile(r'\b(?:viet\s?nam|hanoi|ha noi|hcmc|ho chi minh|saigon|singapore|thailand|bangkok)\b|việt nam|hà nội|hồ chí minh|sài gòn|đà nẵng|thái lan',re.I)
SKILLS = re.compile(r'(?<![\w])(?:C\+\+|C#|\.NET|Node\.js|JavaScript|TypeScript|Python|Java|SQL|PostgreSQL|MySQL|MongoDB|Kubernetes|Docker|Terraform|AWS|Azure|GCP|React|Angular|Linux|Git|CI/CD|Spark|Hadoop|Kafka|HTML|CSS)(?![\w])',re.I)
SKILL_HEADER = re.compile(r'(?im)^\s*(?:[#*\- ]{0,8})(?:skills|technical skills|requirements|qualifications|yêu cầu|kỹ năng)\s*[:：]?', re.I)

def assess(row):
    domain, geo, content, status, reasons, ev = v1_assess(row)
    ev = json.loads(ev); old_reasons = set(reasons); reasons = [x for x in reasons if not x.startswith(('domain_', 'geography_', 'eligibility_'))]
    title = text(row.get('job_title_clean')); fields = ('responsibilities_clean','description_clean','raw_job_text_clean')
    extra = IT_TITLE.search(title); duty = None
    for field in fields:
        value = text(row.get(field))
        for m in IT_DUTY.finditer(value):
            context = value[max(0, m.start()-180):m.start()]
            if field == 'responsibilities_clean' or re.search(r'you will|you.ll|your role|responsibilit|what you|nhiệm vụ|công việc|bạn sẽ', context, re.I):
                duty=(field,m); break
        if duty: break
    education = bool(TECH_EDUCATION.search(title))
    cyber = next(((f, m) for f in fields if (m := CYBER.search(text(row.get(f))))), None)
    if 'domain_conflicting_title' in old_reasons or (domain == 'non_it' and (extra or duty or education)):
        domain='unknown'; reasons.append('domain_non_it_technical_conflict')
    elif AMBIGUOUS.search(title) and not CYBER.search(title) and not extra and not duty and not (re.search(r'security engineer',title,re.I) and cyber):
        domain='unknown'; reasons.append('domain_ambiguous_engineering_title')
    elif domain == 'unknown' and (extra or (duty and row.get('source_id') != 'awesome_jobs_vietnam')):
        domain='it'; reasons.append('domain_explicit_it_title' if extra else 'domain_explicit_it_responsibility')
    else: reasons.append('domain_no_clear_evidence' if domain == 'unknown' else 'domain_v1_'+domain)
    if extra: ev['domain'].append({'field':'job_title_clean','value':extra.group(),'rule':'explicit_it_title_v2'})
    if duty: ev['domain'].append({'field':duty[0],'value':duty[1].group(),'rule':'explicit_it_duty_v2'})
    if cyber and re.search(r'security engineer',title,re.I): ev['domain'].append({'field':cyber[0],'value':cyber[1].group(),'rule':'security_context_v2'})
    # A GitHub issue may describe several positions; a single location must not be assigned to all.
    found=set()
    if row.get('source_id') != 'awesome_jobs_vietnam':
        for field in ('description_clean','raw_job_text_clean'):
            for line in GEO_LINE.finditer(text(row.get(field))):
                for match in GEO.finditer(line.group(1)):
                    v=match.group(); region='outside_vietnam' if re.search(r'singapore|thailand|bangkok|thái lan',v,re.I) else 'vietnam'
                    found.add(region); ev['geography'].append({'field':field,'value':line.group().strip(),'rule':'explicit_work_location_line_v2'})
    if len(found)>1 or (found and geo != 'unknown' and geo not in found): geo='unknown'; reasons.append('geography_conflict_v2')
    elif geo=='unknown' and len(found)==1 and 'geography_conflict' not in old_reasons and not any('conflict' in x for x in row.get('normalization_flags') or []): geo=next(iter(found)); reasons.append('geography_explicit_jd_location')
    else: reasons.append('geography_conflict_v1' if 'geography_conflict' in old_reasons else 'geography_no_clear_evidence' if geo == 'unknown' else 'geography_v1_'+geo)
    skills=[]
    for field in ('requirements_clean','responsibilities_clean','description_clean','raw_job_text_clean','description_transformed_clean'):
        value=text(row.get(field)); matches=list(SKILLS.finditer(value))
        if len({m.group().casefold() for m in matches}) >= 2 and (field in ('requirements_clean','description_transformed_clean') or SKILL_HEADER.search(value)):
            skills=[{'field':field,'value':m.group(),'rule':'two_technical_skills_in_skill_context'} for m in matches[:10]]; break
    extractable=bool(skills); ev['skill_extractability']=skills
    reasons.append('skill_extractable' if extractable else 'skill_evidence_insufficient')
    if domain=='non_it' or geo=='outside_vietnam' or content=='insufficient': status='not_eligible'
    elif domain=='it' and geo=='vietnam' and content=='full_jd': status='eligible'
    else: status='needs_review'
    reasons.append('eligibility_'+status)
    return domain,geo,content,status,reasons,json.dumps(ev,ensure_ascii=False,sort_keys=True),extractable

def run(root):
    root=Path(root); st=root/'data/staging'; reports=root/'data/reports'
    old_path=st/'eligible_jds.parquet'; inp=st/'normalized_jds.parquet'; mapping=st/'duplicate_mapping.parquet'
    prior=json.loads((reports/'eligibility_report.json').read_text()); norm=json.loads((reports/'normalization_report.json').read_text())
    if sha(old_path)!=prior['output_sha256'] or sha(inp)!=prior['input_sha256'] or sha(mapping)!=norm['mapping_sha256']: raise ValueError('Input checksum mismatch')
    t=pq.read_table(old_path); rows=t.to_pylist(); maps=pq.read_table(mapping).to_pylist()
    if len(rows)!=prior['output_groups'] or len(maps)!=norm['mapped_raw_records'] or len({x['record_id'] for x in maps})!=len(maps): raise ValueError('Provenance count mismatch')
    names=['domain_status','geography_status','content_status','eligibility_status','eligibility_reason_codes','eligibility_evidence']
    for name in names: t=t.rename_columns([('v1_'+n if n==name else n) for n in t.column_names])
    results=[assess(r) for r in rows]; names += ['skill_extractable']
    for i,(name,typ) in enumerate(zip(names,[pa.string()]*4+[pa.list_(pa.string()),pa.string(),pa.bool_()])): t=t.append_column(name,pa.array([r[i] for r in results],type=typ))
    md=dict(t.schema.metadata or {}); md.update({b'eligibility_version':VERSION.encode(),b'eligibility_v1_sha256':sha(old_path).encode(),b'eligibility_rules_sha256':sha(Path(__file__)).encode()}); t=t.replace_schema_metadata(md)
    out=st/'eligible_jds_v2.parquet'; pq.write_table(t,out)
    total=defaultdict(Counter); by=defaultdict(lambda:defaultdict(Counter)); transitions=defaultdict(Counter); source_transitions=defaultdict(lambda:defaultdict(Counter)); reasons=defaultdict(lambda:defaultdict(Counter))
    for row,result in zip(rows,results):
        for name,val in zip(names[:4]+['skill_extractable'],list(result[:4])+[str(result[6]).lower()]):
            total[name][val]+=1; by[row['source_id']][name][val]+=1
        for name,val in zip(names[:4],result[:4]):
            transitions[name][str(row[name])+' -> '+str(val)]+=1
            source_transitions[row['source_id']][name][str(row[name])+' -> '+str(val)]+=1
            if val=='unknown' or (name=='content_status' and val!='full_jd'):
                for reason in result[4]:
                    if reason.startswith(name.split('_')[0]+'_'): reasons[row['source_id']][name][reason]+=1
    report={'generated_at':datetime.now(timezone.utc).isoformat(),'version':VERSION,'rules_sha256':sha(Path(__file__)),'v1_sha256':sha(old_path),'normalized_sha256':sha(inp),'mapping_sha256':sha(mapping),'output_sha256':sha(out),'groups':len(rows),'mapped_raw_records':len(maps),'v1_totals':prior['totals'],'v1_by_source':prior['by_source'],'v2_totals':total,'by_source':by,'transitions':transitions,'transitions_by_source':source_transitions,'unresolved_reasons_by_source':reasons,'gemini':'not used; legacy splits require provenance and exact input reconciliation'}
    (reports/'eligibility_v2_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='.');run(p.parse_args().root)
