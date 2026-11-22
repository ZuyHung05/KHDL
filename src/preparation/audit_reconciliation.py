"""Audit legacy grouping, prior near pairs and flagged cleaning records."""
import argparse,csv,hashlib,html,json,re
from collections import Counter,defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from bs4 import BeautifulSoup
import pyarrow.parquet as pq
from src.collection import runner
from . import deduplicate as d

ROOT=d.ROOT


def compact(text):
    return re.sub(r'[^\w+#]','',d.norm(text))


def inspect_cleaning(record):
    fields=[]
    for field in ('job_title','description','requirements','raw_job_text','description_transformed','responsibilities'):
        a,b=record.get(field),record.get(field+'_clean')
        if a is None or b is None:continue
        try:
            if field=='requirements':a=json.loads(a);b=json.loads(b)
        except (ValueError,TypeError):
            fields.append({'field':field,'status':'uncertain_invalid_json'});continue
        if not isinstance(a,str) or not isinstance(b,str):continue
        a=d.cleaning.unescape_all(a)
        if re.search(r'(?i)</?(?:p|div|span|li|ul|ol|h[1-6]|br|a|table)\b',a):
            a=BeautifulSoup(a,'html.parser').get_text('')
        x,y=compact(a),compact(b)
        ops=SequenceMatcher(None,x,y,autojunk=False).get_opcodes()
        lost=sum(j-i for op,i,j,k,l in ops if op in ('delete','replace'))
        fields.append({'field':field,'visible_alphanumeric_plus_hash_chars_before':len(x),'visible_alphanumeric_plus_hash_chars_after':len(y),'unmatched_before_chars':lost,'status':'no_loss_detected_in_selected_characters' if lost==0 else 'uncertain_unmatched_characters'})
    status='uncertain' if not fields or any(x['status'].startswith('uncertain') for x in fields) else 'no_loss_detected_in_selected_characters'
    return {'record_id':record['record_id'],'source_id':record['source_id'],'status':status,'fields':fields,'review_method':'automated independent visible-character comparison; punctuation, links and semantic meaning need human review'}


def classify_pair(a,b):
    id1=d.topcv_posting_id(a.get('source_url'));id2=d.topcv_posting_id(b.get('source_url'))
    title=d.norm(a.get('job_title_clean'));title2=d.norm(b.get('job_title_clean'))
    if id1 and id1==id2 and title and title==title2 and d.compatible(a,b):
        return 'confirmed_duplicate','same_topcv_numeric_posting_id_same_title_no_company_location_conflict'
    if id1 and id2 and id1!=id2:
        return 'distinct','different_topcv_posting_ids_distinct_postings_reposts_possible'
    # Different Careers@Gov source IDs are distinct posting records, but they may
    # be the same vacancy reposted. This remains uncertain without more evidence.
    return 'uncertain','similarity_or_different_source_id_alone_does_not_prove_vacancy_identity'


def main():
    reportdir=ROOT/'data/reports';stage=ROOT/'data/staging'
    old=json.loads((reportdir/'dedup_report.json').read_text());qa=json.loads((reportdir/'cleaning_qa_report.json').read_text())
    prior_path=reportdir/'dedup_reconciliation_report.json'
    prior=runner.read_json(prior_path,{})
    current_hash=runner.sha256_file(stage/'cleaned_jds.parquet')
    if prior.get('input_sha256') != current_hash: prior = {}
    if old.get('input_sha256')!=current_hash:
        raise ValueError('Audit baseline belongs to a different cleaned dataset')
    records=pq.read_table(stage/'cleaned_jds.parquet').to_pylist();by={r['record_id']:r for r in records}
    qrecords=[inspect_cleaning(by[x['record_id']]) for x in qa['records'] if x['finding']=='needs_review']
    audit_path=reportdir/'near_duplicate_audit.csv'
    if audit_path.exists() and prior:
        with audit_path.open(encoding='utf-8-sig',newline='') as f:
            pairs=[{k:v for k,v in row.items() if k not in ('audit_status','audit_reason','audit_method')} for row in csv.DictReader(f)]
        if len(pairs)!=prior['before']['near_candidates']:
            raise ValueError('Frozen near-pair audit does not match baseline report')
    else:
        if old.get('version') not in ('dedup_v1','dedup_v2'):raise ValueError('Unsupported dedup baseline version')
        with (reportdir/'near_duplicate_candidates.csv').open(encoding='utf-8-sig',newline='') as f:pairs=list(csv.DictReader(f))
    near=[]
    for x in pairs:
        status,reason=classify_pair(by[x['record_id_a']],by[x['record_id_b']]);near.append({**x,'audit_status':status,'audit_reason':reason,'audit_method':'rule_based_not_human'})
    sample=[]
    for status in ('confirmed_duplicate','distinct','uncertain'):
        candidates=sorted((x for x in near if x['audit_status']==status),key=lambda x:hashlib.sha256(('audit42'+x['record_id_a']+x['record_id_b']).encode()).hexdigest())[:5]
        for x in candidates:
            a,b=by[x['record_id_a']],by[x['record_id_b']]
            sample.append({'record_id_a':x['record_id_a'],'record_id_b':x['record_id_b'],'status':status,'reason':x['audit_reason'],'source_id_a':a['source_id'],'source_id_b':b['source_id'],'url_a':a.get('source_url'),'url_b':b.get('source_url'),'source_job_id_a':a.get('source_job_id'),'source_job_id_b':b.get('source_job_id'),'same_normalized_company':bool(d.norm(a.get('company_name')) and d.norm(a.get('company_name'))==d.norm(b.get('company_name'))),'same_normalized_title':d.norm(a.get('job_title_clean'))==d.norm(b.get('job_title_clean'))})
    runner.write_json(reportdir/'near_duplicate_audit_sample.json',{'method':'up to five pairs per audit status, deterministic hash seed audit42; rule evidence not a human or gold judgment','pairs':sample})
    with (reportdir/'near_duplicate_audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=list(pairs[0]) + ['audit_status','audit_reason','audit_method'] if pairs else ['record_id_a','record_id_b','audit_status','audit_reason','audit_method']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(near)
    legacy,_=d.legacy_mapping(records);groups=defaultdict(list)
    for r in records:
        if r['record_id'] in legacy:groups[legacy[r['record_id']]].append(r)
    splits=[]
    for key,rs in sorted(groups.items()):
        if len(rs)<2:continue
        src=sorted({r['source_id'] for r in rs})
        splits.append({'legacy_jd_id':key,'record_ids':[r['record_id'] for r in rs],'source_ids':src,'record_count':len(rs),'company_present':sum(bool(d.norm(r.get('company_name'))) for r in rs),'url_present':sum(bool(d.norm_url(r.get('source_url'))) for r in rs),'source_job_ids_distinct':len({d.norm(r.get('source_job_id')) for r in rs if d.norm(r.get('source_job_id'))}),'reason':'legacy_exact_title_company_description_without_url; current lacks trusted posting_identity' if not any(d.norm_url(r.get('source_url')) for r in rs) else 'legacy_group_split_due_to_stricter_identity','status':'uncertain_needs_review'})
    runner.write_json(reportdir/'legacy_dedup_audit.json',{'legacy_unique':len(groups),'split_groups':len(splits),'groups':splits})
    runner.write_json(reportdir/'cleaning_qa_audit.json',{'review_count':len(qrecords),'results':dict(Counter(x['status'] for x in qrecords)),'records':qrecords,'limitations':['Automated review does not prove semantic equivalence or punctuation preservation.','No human review claimed; source and clean strings remain in staging for manual inspection.']})
    after=d.run()
    before=prior.get('before') or {'input_records':old['input_records'],'groups':old['output_jds'],'merged_records':old['merged_records'],'near_candidates':len(near)}
    summary={'generated_at':runner.now(),'input_sha256':current_hash,'before':before,'after':{'input_records':after['input_records'],'groups':after['output_jds'],'merged_records':after['merged_records'],'near_candidates':after['near_candidates'],'duplicate_clusters':after['duplicate_clusters']},'near_audit_counts':dict(Counter(x['audit_status'] for x in near)),'near_audit_method':'automated identity rules, not independent human labeling; distinct means different source postings, reposts still possible','legacy_split_groups':len(splits),'legacy_split_by_source':dict(Counter('+'.join(x['source_ids']) for x in splits)),'legacy_status':'all legacy splits remain uncertain for label transfer; per-group evidence in legacy_dedup_audit.json','cleaning_audit_counts':dict(Counter(x['status'] for x in qrecords)),'cleaning_audit_total':len(qrecords),'limitations':['Similarity alone never confirms duplicate.','No gold review or manual QA has been performed.','TopCV numeric job ID treated as stable posting identity; different posting IDs can still represent reposts.']}
    runner.write_json(reportdir/'dedup_reconciliation_report.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':argparse.ArgumentParser(description=__doc__).parse_args();main()
