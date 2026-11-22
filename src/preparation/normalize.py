"""Normalize explicit structured source fields; preserve all input columns."""
from __future__ import annotations
import argparse,hashlib,json,math,os,re,tempfile
from collections import Counter,defaultdict
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from src.collection import runner
from . import unified

ROOT=unified.ROOT
RULES=ROOT/'configs/field_normalization.yaml'
INPUT=ROOT/'data/staging/deduplicated_jds.parquet'
MAPPING=ROOT/'data/staging/duplicate_mapping.parquet'
OUTPUT=ROOT/'data/staging/normalized_jds.parquet'
REPORT=ROOT/'data/reports/normalization_report.json'
SENTINELS={'na','n/a','nan','null','none','not specified','not applicable','unknown','không rõ'}
NORM_FIELDS=('location_normalized','country_normalized','experience_years_min_normalized','experience_years_max_normalized','seniority_normalized','employment_type_normalized','work_arrangement_normalized','posted_at_normalized')


def value(x):
    if x is None:return None
    if isinstance(x,str):
        if not x.strip() or x.strip().casefold() in SENTINELS:return None
        return x.strip()
    return x


def parse_json(x):
    if x is None:return None
    try:return json.loads(x)
    except (TypeError,ValueError):return None


def exact_match(x, dictionary):
    x=value(x)
    if not isinstance(x,str):return []
    normalized=runner.normalized(x).rstrip(',').strip()
    return sorted(k for k,aliases in dictionary.items() if normalized in [runner.normalized(a) for a in aliases])


def extract_locations(text, dictionary):
    text=value(text)
    if not isinstance(text,str):return []
    text=runner.normalized(text)
    found=set()
    for canonical,aliases in dictionary.items():
        for alias in aliases:
            alias=runner.normalized(alias)
            if re.search(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',text):found.add(canonical);break
    return sorted(found)


def normalize_record(row,rules):
    flags=[]; evidence={}; result={k:None for k in NORM_FIELDS}
    city=value(row.get('city'));loc=value(row.get('location_raw'))
    city_matches=exact_match(city,rules['locations']);loc_matches=extract_locations(loc,rules['locations'])
    if city and not city_matches:flags.append('location_city_unrecognized')
    if city_matches and loc_matches and not set(city_matches).issubset(loc_matches):flags.append('location_conflict')
    else:
        found=sorted(set(city_matches)|set(loc_matches))
        if found:result['location_normalized']=found;evidence['location_normalized']={'city':city,'location_raw':loc}
        elif loc and runner.normalized(str(loc)) not in ('remote','vn','vietnam','việt nam','thailand'):flags.append('location_unrecognized')
    # Country is used only when explicitly present as an entire country value in country or location_raw.
    source_country=value(row.get('country'));country=exact_match(source_country,rules['countries']);country_loc=exact_match(loc,rules['countries'])
    if source_country and not country:flags.append('country_unrecognized')
    if country and country_loc and set(country)!=set(country_loc):flags.append('country_conflict')
    else:
        found=sorted(set(country)|set(country_loc))
        if found:result['country_normalized']=found;evidence['country_normalized']={'country':source_country,'location_raw':loc if country_loc else None}
    sid=row.get('source_id');rawexp=parse_json(row.get('experience_raw'))
    for bound in ('min','max'):
        key='experience_years_'+bound;v=row.get(key)
        if v is None:continue
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=60:
            flags.append('experience_'+bound+'_invalid');continue
        # Careers@Gov uses zeros even where the human-readable experience is absent.
        if sid=='careersgovsg' and not value(rawexp):flags.append('experience_without_source_text');continue
        if sid=='careersgovsg' and v==0 and row.get('experience_years_min')==0 and row.get('experience_years_max')==0:
            flags.append('experience_zero_range_ambiguous');continue
        result[key+'_normalized']=float(v);evidence[key+'_normalized']={key:v,'experience_raw_present':bool(value(rawexp))}
    lo=result['experience_years_min_normalized'];hi=result['experience_years_max_normalized']
    if lo is not None and hi is not None and lo>hi:
        result['experience_years_min_normalized']=result['experience_years_max_normalized']=None;flags.append('experience_range_conflict')
    senior=value(row.get('seniority_source'))
    if isinstance(senior,str):
        parts=[x.strip() for x in re.split(r'[,;/]',senior) if x.strip()];matched=[];unknown=[]
        for part in parts:
            m=exact_match(part,rules['seniority']);matched.extend(m)
            if not m:unknown.append(part)
        if len(set(matched))==1 and not unknown:
            result['seniority_normalized']=matched[0];evidence['seniority_normalized']={'seniority_source':senior}
        elif len(set(matched))>1:flags.append('seniority_multiple')
        else:flags.append('seniority_unrecognized')
    elif value(row.get('source_level_fields')):flags.append('seniority_source_codes_unmapped')
    employment=value(row.get('employment_type'));terms=[employment] if employment else []
    if sid=='data_job_analysis':
        extra=parse_json(row.get('source_extra')) or {}
        terms.extend(v for k in ('W_Term_2','W_Term_3','W_Term_4') if (v:=value(extra.get(k))))
    work_terms=[];found_employment=set()
    for term in terms:
        found=exact_match(term,rules['employment_type']);work=exact_match(term,rules['work_arrangement'])
        if found:found_employment.update(found)
        elif work:work_terms.extend(work)
        elif runner.normalized(str(term)) in ('permanent/contract','contract / freelance'):
            found_employment.update(('permanent','contract') if runner.normalized(str(term))=='permanent/contract' else ('contract','freelance'))
        else:flags.append('employment_unrecognized')
    if found_employment:
        result['employment_type_normalized']=sorted(found_employment);evidence['employment_type_normalized']={'source_terms':terms}
        if len(found_employment)>1:flags.append('employment_multiple')
    arr=value(row.get('work_arrangement'));arrvals=exact_match(arr,rules['work_arrangement'])
    # Full-time and part-time express schedule, not work arrangement.
    if arr and not arrvals:flags.append('work_arrangement_unrecognized')
    loc_arr=exact_match(loc,rules['work_arrangement'])
    flag=parse_json(row.get('source_remote_flag'))
    remote=['remote'] if flag is True or flag=='1' or (isinstance(flag,int) and not isinstance(flag,bool) and flag==1) else []
    combined=set(arrvals+loc_arr+remote+work_terms)
    if len(combined)>1:flags.append('work_arrangement_conflict')
    elif combined:
        result['work_arrangement_normalized']=next(iter(combined));evidence['work_arrangement_normalized']={'work_arrangement':arr,'location_raw':loc if loc_arr else None,'remote_flag':flag if remote else None,'source_terms':terms if work_terms else []}
    posted=row.get('posted_at')
    if posted is not None:
        if getattr(posted,'tzinfo',None) is None:flags.append('posted_at_timezone_missing')
        else:result['posted_at_normalized']=posted;evidence['posted_at_normalized']={'source':'posted_at'}
    result['normalization_status']='needs_review' if flags else ('normalized' if any(result[k] is not None for k in NORM_FIELDS) else 'no_evidence')
    result['normalization_flags']=sorted(set(flags));result['normalization_evidence']=json.dumps(evidence,ensure_ascii=False,sort_keys=True)
    return result


def run():
    rules=yaml.safe_load(RULES.read_text(encoding='utf-8'));input_hash=runner.sha256_file(INPUT);mapping_hash=runner.sha256_file(MAPPING)
    table=pq.read_table(INPUT);mt=pq.read_table(MAPPING,columns=['record_id','jd_id','representative_record_id','status'])
    rows=table.to_pylist();mapping=mt.to_pylist();ids=[r['jd_id'] for r in rows]
    if len(set(ids))!=len(ids) or any(not x for x in ids):raise ValueError('Invalid deduplicated JD IDs')
    if len({m['record_id'] for m in mapping})!=len(mapping) or set(ids)!={m['jd_id'] for m in mapping}:raise ValueError('Duplicate mapping does not reconcile')
    reps=[m for m in mapping if m['status']=='representative']
    repmap={m['jd_id']:m['record_id'] for m in reps}
    if len(reps)!=len(rows) or len(repmap)!=len(rows) or any(repmap.get(r['jd_id'])!=r['record_id'] for r in rows):raise ValueError('Representatives do not reconcile')
    members=defaultdict(set)
    for m in mapping:members[m['jd_id']].add(m['record_id'])
    for row in rows:
        saved=json.loads(row['members_json'])
        if row['member_count']!=len(members[row['jd_id']]) or {m['record_id'] for m in saved}!=members[row['jd_id']]:
            raise ValueError('Cluster membership does not match duplicate mapping')
    result=[normalize_record(r,rules) for r in rows]
    schema_types={'location_normalized':pa.list_(pa.string()),'country_normalized':pa.list_(pa.string()),'experience_years_min_normalized':pa.float64(),'experience_years_max_normalized':pa.float64(),'seniority_normalized':pa.string(),'employment_type_normalized':pa.list_(pa.string()),'work_arrangement_normalized':pa.string(),'posted_at_normalized':pa.timestamp('us',tz='UTC'),'normalization_status':pa.string(),'normalization_flags':pa.list_(pa.string()),'normalization_evidence':pa.string()}
    output=table
    for k,t in schema_types.items():
        if k in output.column_names:raise ValueError('Input already normalized: '+k)
        output=output.append_column(k,pa.array([r[k] for r in result],type=t))
    rule_hash=runner.sha256_file(RULES);output=output.replace_schema_metadata({**(table.schema.metadata or {}),b'normalization_version':rules['version'].encode(),b'normalization_rules_sha256':rule_hash.encode(),b'dedup_input_sha256':input_hash.encode(),b'duplicate_mapping_sha256':mapping_hash.encode()})
    coverage=defaultdict(lambda:defaultdict(Counter));statuses=defaultdict(Counter);flagcounts=defaultdict(Counter)
    inputs={'location_normalized':['city','location_raw'],'country_normalized':['country','location_raw'],'experience_years_min_normalized':['experience_years_min'],'experience_years_max_normalized':['experience_years_max'],'seniority_normalized':['seniority_source','source_level_fields'],'employment_type_normalized':['employment_type'],'work_arrangement_normalized':['work_arrangement','location_raw','source_remote_flag'],'posted_at_normalized':['posted_at']}
    for old,new in zip(rows,result):
        sid=old['source_id'];statuses[sid][new['normalization_status']]+=1;flagcounts[sid].update(new['normalization_flags'])
        for field,src in inputs.items():
            c=coverage[sid][field];c['records']+=1;c['input_nonempty']+=bool(any(value(old.get(s)) is not None for s in src));c['normalized']+=new[field] is not None
    for groups in coverage.values():
        for c in groups.values():c['unknown']=c['records']-c['normalized'];c['normalized_pct']=round(100*c['normalized']/c['records'],2);c['unknown_pct']=round(100*c['unknown']/c['records'],2)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True);REPORT.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.normalize-',suffix='.parquet',dir=OUTPUT.parent);os.close(fd)
    try:
        pq.write_table(output,tmp,compression='snappy')
        if runner.sha256_file(INPUT)!=input_hash or runner.sha256_file(MAPPING)!=mapping_hash:raise ValueError('Input changed during normalization')
        if pq.ParquetFile(tmp).metadata.num_rows!=len(rows):raise ValueError('Output row count mismatch')
        out_hash=runner.sha256_file(tmp);os.replace(tmp,OUTPUT)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    summary={'generated_at':runner.now(),'normalization_version':rules['version'],'rules_sha256':rule_hash,'input_sha256':input_hash,'mapping_sha256':mapping_hash,'output_sha256':out_hash,'input_groups':len(rows),'output_groups':output.num_rows,'mapped_raw_records':len(mapping),'status_by_source':statuses,'flags_by_source':flagcounts,'coverage_by_source':coverage,'coverage_note':'input_nonempty is field availability, not proof of equivalent meaning; unknown includes missing, ambiguous and unmapped'}
    runner.write_json(REPORT,summary)
    return summary


def main():
    argparse.ArgumentParser(description=__doc__).parse_args();r=run();print(json.dumps({'input_groups':r['input_groups'],'output_groups':r['output_groups'],'mapped_raw_records':r['mapped_raw_records'],'status_by_source':r['status_by_source']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
