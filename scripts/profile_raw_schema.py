"""Profile current raw snapshots without changing source records."""
import csv
import json
import math
import yaml
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from src.collection.runner import registry, rows, sha256_file

ROOT = Path(__file__).resolve().parents[1]
SENTINELS = {'null', 'none', 'nan', 'n/a', 'na'}
MAP = {
 'it_job_posting': {'title':'job_title','company':'company_name','company_image_url':'company_image_url','location':'location_raw','description':'description','site':'platform','job_url':'source_url','it_role_type':'source_role_label','main_programming_languages':'source_skill_labels','key_technologies':'source_skill_labels','city':'city'},
 'dpl_evaluation': {'job_id':'source_job_id','tên job':'job_title','normalized_job_title':'source_role_label','company':'company_name','job_family':'source_role_family','domain':'industry','levels':'seniority_source','mức lương':'salary_raw','skill_requirements':'source_skill_labels','experience':'experience_raw','education_requirements':'education_requirements','language_requirements':'language_requirements','must_have_requirements':'requirements','preferred_requirements':'preferred_requirements','soft_skills':'source_skill_labels','behavioral_traits':'behavioral_traits','certification_requirements':'certification_requirements','portfolio_requirements':'portfolio_requirements','benefits':'benefits','location':'location_raw','work_mode':'work_arrangement','employment_type':'employment_type','raw job':'raw_job_text'},
 'vietjobs': {'job_title':'job_title','location':'location_raw','country':'country','qualifications':'education_requirements','technical_skills':'source_skill_labels','soft_skills':'source_skill_labels','languages_required':'language_requirements','experience_required':'experience_raw','salary':'salary_raw','contract_type':'employment_type','working_hours':'working_hours','benefits':'benefits','description':'description','requirements_text':'requirements','category':'source_category','salary_min':'salary_min','salary_max':'salary_max','salary_avg':'salary_average'},
 'data_job_analysis': {'Job_ID':'source_job_id','Job_Title':'job_title','Min_YOE':'experience_years_min','Est_Salary':'salary_estimate','JD_Trans':'description_transformed','Location':'location_raw','VN':'source_vietnam_flag','Remote':'source_remote_flag','W_Term':'employment_type','W_Term_2':'employment_type','W_Term_3':'employment_type','W_Term_4':'employment_type','Data_Engineer':'source_role_flags','Data_Analyst':'source_role_flags','Data_Scientist':'source_role_flags','Business_Analyst':'source_role_flags','Business_Intelligence':'source_role_flags','Combined_role':'source_role_flags','Others':'source_role_flags','L1':'source_level_fields','L2':'source_level_fields','L3':'source_level_fields','L4':'source_level_fields','MinL':'source_level_fields'},
 'careersgovsg': {'platform':'platform','postingNo':'source_posting_id','jobId':'source_job_id','jobTitle':'job_title','agency':'company_name','agencyId':'company_source_id','agencyDescription':'company_description','startDate':'posted_at','closingDate':'closing_at','closingDateText':'closing_date_text','remainingDays':'source_remaining_days','employmentType':'employment_type','employmentTypeCode':'employment_type_code','experienceRequired':'experience_raw','experienceYearsMin':'experience_years_min','experienceYearsMax':'experience_years_max','field':'source_category','fieldCode':'source_category_code','functionalArea':'functional_area','functionalAreaCode':'functional_area_code','industry':'industry','educationCode':'education_code','isNew':'source_new_flag','location':'location_raw','jobDescription':'description','jobResponsibilities':'responsibilities','jobRequirements':'requirements','category':'source_category','workArrangement':'work_arrangement'},
 'ady201m': {'name':'job_title','Mô tả công việc':'description','Yêu cầu ứng viên':'requirements','Quyền lợi':'benefits','Cách thức ứng tuyển':'application_instructions','source_url':'source_url','crawled_at':'source_crawled_at'},
 'awesome_jobs_vietnam': {'number':'source_job_id','title':'job_title','body':'raw_job_text','html_url':'source_url','state':'source_status','created_at':'source_created_at','updated_at':'source_updated_at','closed_at':'source_closed_at'} }
TEXT_FIELDS = {'description','description_transformed','raw_job_text','requirements','preferred_requirements','responsibilities'}

def kind(v):
 if v is None:return 'null'
 if isinstance(v,bool):return 'boolean'
 if isinstance(v,str):return 'string'
 if isinstance(v,int):return 'integer'
 if isinstance(v,float):return 'number'
 if isinstance(v,list):return 'array'
 if isinstance(v,dict):return 'object'
 return type(v).__name__

def percentile(a,q):
 if not a:return None
 s=sorted(a);x=(len(s)-1)*q;lo=int(x);hi=math.ceil(x);return round(s[lo]+(s[hi]-s[lo])*(x-lo),2)

def summarize_lengths(values):
 return {'unit':'unicode_codepoints','count':len(values),'min':min(values) if values else None,'mean':round(sum(values)/len(values),2) if values else None,'median':percentile(values,.5),'p90':percentile(values,.9),'max':max(values) if values else None}

def main():
 reports=ROOT/'data/reports';reports.mkdir(parents=True,exist_ok=True)
 custom=ROOT/'configs/source_adapter_mappings.yaml'
 if custom.exists(): MAP.update(yaml.safe_load(custom.read_text()) or {})
 known={s['source_id']:s for s in registry()};found={p.parent.name:p for p in (ROOT/'data/raw').glob('*/latest.json')}; sources={};mapping=[];issues=[]
 if not found: raise ValueError('No latest raw snapshots; run ingestion first')
 for sid,pointer in sorted(found.items()):
  if sid not in MAP: raise ValueError('Unsupported source schema: '+sid+'; add explicit mapping in configs/source_adapter_mappings.yaml')
  source=known.get(sid)
  if not source:issues.append({'source_id':sid,'reason':'latest exists but source registry missing'});continue
  latest=json.loads(pointer.read_text(encoding='utf-8'))
  for entry in latest.get('files',{}).values():
   spec=next((x for x in source['files'] if x['path']==entry['source_file']),None)
   if not spec:issues.append({'source_id':sid,'reason':'latest file not configured','source_file':entry['source_file']});continue
   f=(pointer.parent/entry['snapshot']/Path(entry['source_file']).name).resolve()
   if not f.is_relative_to(pointer.parent.resolve()) or sha256_file(f)!=entry['file_sha256']:raise ValueError('Snapshot invalid: '+str(f))
   counts=defaultdict(Counter);lengths=defaultdict(list);total=0
   for row in rows(f,spec):
    if not isinstance(row,dict):raise ValueError('Non-object record: '+str(f))
    total+=1
    for key,value in row.items():
     c=counts[key];c['present']+=1;c['type_'+kind(value)]+=1
     if value is None:c['null']+=1
     elif isinstance(value,str) and not value.strip():c['empty']+=1
     elif isinstance(value,(list,dict)) and not value:c['empty']+=1
     elif isinstance(value,str) and value.strip().casefold() in SENTINELS:c['sentinel_literal']+=1
     else:
      c['nonempty']+=1
      if MAP.get(sid,{}).get(key) in TEXT_FIELDS:
       if isinstance(value,str):lengths[key].append(len(value))
       else:c['nonstring_text']+=1
   if total == 0: raise ValueError('Empty source snapshot: '+sid)
   fields={}
   for key,c in sorted(counts.items()):
    miss=total-c['present'];null=c['null'];empty=c['empty'];sent=c['sentinel_literal'];invalid=miss+null+empty
    obj={'observed_types':{k[5:]:v for k,v in c.items() if k.startswith('type_')},'missing':miss,'null':null,'empty':empty,'sentinel_literal':sent,'nonempty':c['nonempty'],'missing_pct':round(100*miss/total,2) if total else 0,'null_pct':round(100*null/total,2) if total else 0,'empty_pct':round(100*empty/total,2) if total else 0,'sentinel_literal_pct':round(100*sent/total,2) if total else 0,'missing_null_empty_pct':round(100*invalid/total,2) if total else 0}
    if MAP.get(sid,{}).get(key) in TEXT_FIELDS:obj['text_length']=summarize_lengths(lengths[key]);obj['nonstring_text_count']=c['nonstring_text']
    fields[key]=obj
    target=MAP.get(sid,{}).get(key,'source_extra')
    note='Raw source field retained in source_extra; meaning requires verification.' if target=='source_extra' else ''
    if key in ('JD_Trans','raw job','body'):note={'JD_Trans':'Translated/transformed text; do not claim original description.','raw job':'Full raw JD text; not necessarily a description-only field.','body':'GitHub issue body may describe multiple jobs and contain contact information.'}[key]
    if key in ('jobId','postingNo'):note='Identifier semantics vary by platform; use composite with platform.'
    mapping.append({'source_id':sid,'source_file':entry['source_file'],'source_field':key,'observed_types':'|'.join(sorted(k[5:] for k in c if k.startswith('type_'))),'unified_field':target,'mapping_note':note})
   sources.setdefault(sid,{'repository':source['repository'],'files':[]})['files'].append({'source_file':entry['source_file'],'snapshot':entry['snapshot'],'file_sha256':entry['file_sha256'],'record_count':total,'fields':fields})
 profile={'generated_at':datetime.now(timezone.utc).isoformat(),'definition':{'unit':'raw record; no dedup','missing':'key absent from a record','null':'JSON null or Python None','empty':'empty or whitespace-only string, empty array or object','sentinel_literal':'case-insensitive literal null/none/nan/n/a/na; counted separately, not treated as null','rates':'percentage of all records in that file','csv_types':'CSV values are parsed as strings; inferred datatypes are proposals only','length':'Unicode codepoints of nonempty string, no normalization'},'sources':sources,'unavailable_or_unmapped':issues,'total_raw_records':sum(f['record_count'] for s in sources.values() for f in s['files'])}
 (reports/'schema_profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 with (reports/'schema_mapping.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['source_id','source_file','source_field','observed_types','unified_field','mapping_note']);w.writeheader();w.writerows(mapping)
 print(json.dumps({'sources':len(sources),'records':profile['total_raw_records'],'fields':len(mapping),'issues':issues},ensure_ascii=False))
if __name__=='__main__':main()
