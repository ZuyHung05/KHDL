"""Validate unified staging against its frozen raw snapshots, without modifying input."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq
from src.collection import runner
from . import unified

ROOT = unified.ROOT
SENTINELS = {'nan','null','n/a','na','none','n.a.','unknown','not specified','không rõ'}
CONTENT_FIELDS = ('description','requirements','raw_job_text','description_transformed')
SHORT_THRESHOLD = 100


def category(value):
    if value is None:return 'null'
    if isinstance(value,str):
        if not value.strip():return 'empty'
        if value.strip().casefold() in SENTINELS:return 'sentinel'
    if isinstance(value,(list,dict)) and not value:return 'empty'
    return 'present'


def useful(value):
    if category(value) != 'present':return False
    if isinstance(value,str):return bool(re.search(r'\w',value,flags=re.UNICODE))
    if isinstance(value,list):return any(useful(x) for x in value)
    return False


def decoded(value):
    if value is None:return None
    try:return json.loads(value)
    except (ValueError,TypeError):return None


def judge(row, structural_errors=()):
    """Status concerns input quality only; no role classification."""
    flags=list(structural_errors)
    title=row.get('job_title')
    if category(title)=='sentinel':flags.append('sentinel:job_title')
    title_ok=useful(title)
    content={name: decoded(row.get(name)) if name=='requirements' else row.get(name) for name in CONTENT_FIELDS}
    for name,value in content.items():
        if category(value)=='sentinel':flags.append('sentinel:'+name)
    desc=content['description'];raw=content['raw_job_text'];trans=content['description_transformed'];req=content['requirements']
    has_desc=useful(desc);has_raw=useful(raw);has_trans=useful(trans);has_req=useful(req)
    if not title_ok:flags.append('missing_or_invalid_title')
    if not any((has_desc,has_raw,has_trans,has_req)):
        flags.append('no_job_content')
        return 'unusable',sorted(set(flags))
    if not title_ok or structural_errors:
        return 'needs_review',sorted(set(flags))
    if has_desc and isinstance(desc,str) and len(desc.strip())>=SHORT_THRESHOLD:
        return 'usable',sorted(set(flags))
    if has_raw and isinstance(raw,str) and len(raw.strip())>=SHORT_THRESHOLD and row.get('source_id')!='awesome_jobs_vietnam':
        return 'usable',sorted(set(flags))
    if has_desc and len(desc.strip())<SHORT_THRESHOLD:flags.append('short_description')
    if has_raw and len(raw.strip())<SHORT_THRESHOLD:flags.append('short_raw_job_text')
    if row.get('source_id')=='awesome_jobs_vietnam' and has_raw:flags.append('issue_body_may_contain_multiple_jobs')
    if has_trans and not (has_desc or has_raw):flags.append('transformed_text_only')
    if has_req and not (has_desc or has_raw or has_trans):flags.append('requirements_only')
    return 'needs_review',sorted(set(flags))


def raw_state(raw, keys):
    if not keys:return 'not_provided'
    present=[raw[k] for k in keys if k in raw]
    if not present:return 'missing'
    cats=[category(v) for v in present]
    # Field-level state reflects usable raw contributors; report raw anomalies separately.
    for state in ('present','sentinel','empty','null'):
        if state in cats:return state
    return 'missing'


def check_type(value, field):
    if value is None:return True
    if field in unified.NUMBER_FIELDS:return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    if field in unified.DATE_FIELDS:
        from datetime import datetime
        return isinstance(value,datetime) and value.tzinfo is not None
    if not isinstance(value,str):return False
    if field in unified.JSON_FIELDS or field in ('source_extra','source_locator'):
        try:json.loads(value);return True
        except (ValueError,TypeError):return False
    return True


def flag_record(row, mapping, raw, index, expected_checksum):
    flags=[];struct=[]
    for key in unified.METADATA:
        if not isinstance(row.get(key),str) or not row[key].strip():struct.append('invalid_provenance:'+key)
    if row.get('snapshot_sha256')!=expected_checksum:struct.append('snapshot_checksum_mismatch')
    try:
        loc=json.loads(row['source_locator'])
        if not isinstance(loc,dict) or loc.get('row_index')!=index:struct.append('invalid_source_locator')
        if row.get('source_id')=='awesome_jobs_vietnam' and loc.get('issue_number')!=raw.get('number'):
            struct.append('issue_number_mismatch')
        expected=hashlib.sha256(unified.encode([row['source_id'],row['source_file'],expected_checksum,loc]).encode()).hexdigest()
        if expected!=row['record_id']:struct.append('record_id_mismatch')
    except (ValueError,TypeError,KeyError):struct.append('invalid_source_locator')
    for field,value in row.items():
        if not check_type(value,field):struct.append('invalid_type:'+field)
        if isinstance(value,str) and field not in unified.JSON_FIELDS and category(value)=='sentinel':flags.append('sentinel:'+field)
    for field in unified.NUMBER_FIELDS:
        value=row.get(field)
        if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and (value<0 or value>100):
            flags.append('unusual_value:'+field)
    u=row.get('source_url')
    if category(u)=='present' and isinstance(u,str):
        try:
            parsed=urlsplit(u)
            if parsed.scheme not in ('http','https') or not parsed.netloc:flags.append('invalid_url:source_url')
        except ValueError:flags.append('invalid_url:source_url')
    for key,value in raw.items():
        target=mapping.get(key)
        if category(value)=='sentinel':flags.append('raw_sentinel:'+key)
        if target in unified.NUMBER_FIELDS|unified.DATE_FIELDS and not unified.missing(value):
            try:unified.convert(value,target)
            except (ValueError,TypeError,OverflowError,OSError):
                reason='sentinel' if category(value)=='sentinel' else ('timezone_missing' if target in unified.DATE_FIELDS and isinstance(value,str) and re.fullmatch(r'\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:\.\d+)?',value) else 'invalid_format')
                flags.append('conversion_error:'+key+':'+reason)
                extra=decoded(row.get('source_extra'))
                if not isinstance(extra,dict) or key not in extra or extra[key]!=value:
                    struct.append('conversion_original_not_preserved:'+key)
    status,reasons=judge(row,struct)
    return status,sorted(set(flags+reasons))


def run(input_path=unified.OUTPUT):
    input_path=Path(input_path);report_dir=ROOT/'data/reports';stage=ROOT/'data/staging'
    profile=runner.read_json(report_dir/'unified_mapping_report.json',{})
    if runner.sha256_file(input_path)!=profile.get('parquet_sha256'):raise ValueError('Staging checksum differs from mapping report')
    table=pq.read_table(input_path); rows=table.to_pylist(); schema=table.schema
    mapping=unified.load_mapping(); sources={s['source_id']:s for s in runner.registry()}
    targets=sorted({v for m in mapping.values() for v in m.values()}-{'source_extra'})
    expected=set(unified.METADATA+targets+['source_extra'])
    if set(schema.names)!=expected:raise ValueError('Parquet schema fields differ from unified mapping')
    for field in schema:
        target=pa.float64() if field.name in unified.NUMBER_FIELDS else pa.timestamp('us',tz='UTC') if field.name in unified.DATE_FIELDS else pa.string()
        if field.type!=target:raise ValueError('Parquet datatype mismatch: '+field.name)
    by_id=Counter(r['record_id'] for r in rows);raw_by_source={};snapshot_info={}
    for sid,info in profile['sources'].items():
        if sid not in sources:raise ValueError('Source not in registry: '+sid)
        for snap in info.get('snapshots',[]):
            name=snap['source_file']; spec=next((f for f in sources[sid]['files'] if f['path']==name),None)
            if not spec:raise ValueError('Source file missing from registry')
            root=ROOT/'data/raw'/sid;path=(root/snap['snapshot']/Path(name).name).resolve()
            if not path.is_relative_to(root.resolve()) or runner.sha256_file(path)!=snap['sha256']:raise ValueError('Raw snapshot checksum mismatch')
            raw_by_source[(sid,name,snap['sha256'])]=list(runner.rows(path,spec));snapshot_info[str(path)]=snap['sha256']
    counts=defaultdict(Counter);missing=defaultdict(Counter);flag_counts=defaultdict(Counter);results=[];seen_locators=set();conversion=defaultdict(Counter)
    for row in rows:
        sid=row.get('source_id');name=row.get('source_file');checksum=row.get('snapshot_sha256');key=(sid,name,checksum)
        if key not in raw_by_source or (sid,name) not in mapping:raise ValueError('Unknown source snapshot in staging')
        try:
            loc=json.loads(row['source_locator']);index=loc['row_index']
            if type(index) is not int or index<0:raise ValueError('invalid row_index')
            raw=raw_by_source[key][index]
        except (IndexError,TypeError,ValueError,KeyError) as e:raise ValueError('Cannot resolve raw locator') from e
        identity=(key,index)
        if identity in seen_locators:raise ValueError('Duplicate raw locator in staging')
        seen_locators.add(identity)
        fmap=mapping[(sid,name)];reverse=defaultdict(list)
        for src,target in fmap.items():
            if target!='source_extra':reverse[target].append(src)
        status,flags=flag_record(row,fmap,raw,index,checksum)
        if not row.get('record_id') or by_id[row['record_id']]!=1:
            flags.append('invalid_or_duplicate_record_id');status='needs_review' if status!='unusable' else status
        for target in targets:
            state=raw_state(raw,reverse[target]);missing[(sid,target)][state]+=1
            missing[(sid,target)]['unified_null' if row.get(target) is None else 'unified_present']+=1
        for flag in flags:
            flag_counts[sid][flag]+=1
            if flag.startswith('conversion_error:'):conversion[sid][flag]+=1
        counts[sid][status]+=1
        results.append({'record_id':row['record_id'],'source_id':sid,'source_file':name,'snapshot_sha256':checksum,'source_locator':row['source_locator'],'quality_status':status,'quality_flags':sorted(set(flags))})
    if len(results)!=len(rows) or len(seen_locators)!=sum(len(x) for x in raw_by_source.values()):raise ValueError('Raw/staging row counts do not reconcile')
    for path,digest in snapshot_info.items():
        if runner.sha256_file(path)!=digest:raise ValueError('Raw changed during validation')
    if runner.sha256_file(input_path)!=profile['parquet_sha256']:raise ValueError('Staging changed during validation')
    flag_schema=pa.schema([('record_id',pa.string()),('source_id',pa.string()),('source_file',pa.string()),('snapshot_sha256',pa.string()),('source_locator',pa.string()),('quality_status',pa.string()),('quality_flags',pa.list_(pa.string()))])
    stage.mkdir(parents=True,exist_ok=True);report_dir.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.quality-',suffix='.parquet',dir=stage);os.close(fd)
    try:
        pq.write_table(pa.Table.from_pylist(results,schema=flag_schema),tmp,compression='snappy')
        os.replace(tmp,stage/'jd_quality_flags.parquet')
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    with (report_dir/'missing_values_report.csv').open('w',encoding='utf-8-sig',newline='') as f:
        columns=['source_id','field','total_records','not_provided','missing','null','empty','sentinel','present','unified_null','unified_present','missing_null_empty_pct_of_provided','missing_pct_of_provided','null_pct_of_provided','empty_pct_of_provided','sentinel_pct_of_provided','not_provided_pct']
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for (sid,field),c in sorted(missing.items()):
            total=sum(counts[sid].values());provided=total-c['not_provided'];miss=c['missing']+c['null']+c['empty']
            writer.writerow({'source_id':sid,'field':field,'total_records':total,**{k:c[k] for k in columns[3:10]},'missing_null_empty_pct_of_provided':round(100*miss/provided,2) if provided else '', **{name+'_pct_of_provided':round(100*c[name]/provided,2) if provided else '' for name in ('missing','null','empty','sentinel')}, 'not_provided_pct':round(100*c['not_provided']/total,2) if total else 0})
    summary={'generated_at':runner.now(),'input_sha256':profile['parquet_sha256'],'total_records':len(rows),'status_counts':dict(Counter(x['quality_status'] for x in results)),'sources':{sid:{'total_records':sum(c.values()),'status_counts':dict(c),'flags':dict(flag_counts[sid]),'conversion_errors':dict(conversion[sid])} for sid,c in counts.items()},'definitions':{'not_provided':'No field mapped for this source/file; independent of row value','missing':'Mapped source keys absent in raw record','null':'Mapped source key exists and is null','empty':'Mapped key exists with empty/whitespace string or empty array/object','sentinel':'Literal missing marker; separate from null and empty','multi_source_fields':'First available category in present, sentinel, empty, null; preserve individual anomalies in quality flags','short_threshold_chars':SHORT_THRESHOLD,'usable':'title plus description >=100 chars, or raw JD text >=100 chars excluding GitHub issue bodies, and no structural errors','needs_review':'content exists but title missing, structural issues, short or transformed-only/requirements-only content, or GitHub issue body','unusable':'no usable description, requirements, raw job text or transformed text','note':'Status is data quality only, not role label; structural file errors abort rather than silently emitting partial data.'}}
    runner.write_json(report_dir/'validation_report.json',summary)
    return summary


def main():
    argparse.ArgumentParser(description=__doc__).parse_args();result=run()
    print(json.dumps({'total':result['total_records'],'status_counts':result['status_counts'],'sources':{k:v['status_counts'] for k,v in result['sources'].items()}},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
