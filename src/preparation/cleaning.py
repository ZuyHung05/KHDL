"""Versioned, non-destructive text cleaning for unified JD staging."""
from __future__ import annotations
import argparse
import hashlib
import html
import json
import os
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from src.collection import runner
from . import unified

ROOT=unified.ROOT
VERSION='jd_text_clean_v1'
FIELDS=('job_title','description','requirements','raw_job_text','description_transformed','responsibilities')
JSON_FIELDS={'requirements'}
SENTINELS={'na','n/a','nan','null','none'}
# Only remove a full, exact standalone site boilerplate line.
BOILERPLATE={'click here to apply'}
TECH=re.compile(r'(?<![\w])(?:C\+\+|C\#|\.NET|Node\.js|CI/CD|AWS\s+EC2)(?![\w])', re.I)
HTML_TAGS=r'html|head|body|p|div|span|strong|b|em|i|ul|ol|li|h[1-6]|br|a|section|article|table|thead|tbody|tr|td|th|pre|code|blockquote'


def unescape_all(text):
    while True:
        new=html.unescape(text)
        if new==text:return text
        text=new


def _clean_once(text, allow_sentinel=False):
    if text is None:return None, False
    if not isinstance(text,str):raise TypeError('Text field must be string')
    if allow_sentinel and text.strip().casefold() in SENTINELS:return None, True
    text=unicodedata.normalize('NFC',unescape_all(text)).replace('\r\n','\n').replace('\r','\n')
    # Preserve visible anchor label and target; ignore href-only references in formatting tags.
    text=re.sub(r'(?is)<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a\s*>',lambda m:m.group(2)+' ('+m.group(1)+')',text)
    text=re.sub(r'(?i)<\s*br\s*/?\s*>','\n',text)
    text=re.sub(r'(?i)<\s*h([1-6])(?:\s[^>]*)?>',lambda m:'\n'+('#'*int(m.group(1)))+' ',text)
    text=re.sub(r'(?i)<\s*li(?:\s[^>]*)?>','\n- ',text)
    text=re.sub(r'(?i)</\s*(?:p|div|li|h[1-6]|section|article|tr|blockquote)\s*>','\n',text)
    text=re.sub(r'(?i)</?\s*(?:'+HTML_TAGS+r')\b[^>]*>','',text)
    text=re.sub(r'\[([^\]\n]+)\]\((https?://[^\s)]+)\)',lambda m:m.group(1)+' ('+m.group(2)+')',text)
    text=re.sub(r'(?m)^\s*```[^\n]*$','',text)
    text=re.sub(r'(?<!\w)(\*\*|__)(?=\S)(.+?)(?<=\S)\1',r'\2',text)
    # Preserve newlines and heading/list markers; remove only control chars and horizontal runs.
    text=''.join(ch if ch in '\n\t' or unicodedata.category(ch) not in ('Cc','Cf') else '' for ch in text)
    lines=[]
    for line in text.split('\n'):
        line=re.sub(r'[^\S\n]+',' ',line).strip()
        if line.casefold() in BOILERPLATE:continue
        lines.append(line)
    text=re.sub(r'\n{3,}','\n\n','\n'.join(lines)).strip()
    return (text if text else None), False


def clean_text(text, allow_sentinel=False):
    """Apply the same rules until stable, including nested entity/markup forms."""
    seen=set()
    while text is not None:
        if text in seen:
            raise ValueError('Cleaning rules did not converge')
        seen.add(text)
        result,sentinel=_clean_once(text, allow_sentinel)
        if sentinel:return None,True
        if result==text:return result,False
        text=result
    return None,False


def clean_json_value(value):
    if isinstance(value,str):
        out,sentinel=clean_text(value);return out,int(sentinel)
    if isinstance(value,list):
        vals=[clean_json_value(v) for v in value];return [v for v,_ in vals],sum(n for _,n in vals)
    if isinstance(value,dict):
        vals={k:clean_json_value(v) for k,v in value.items()};return {k:v for k,(v,_) in vals.items()},sum(n for _,n in vals.values())
    return value,0


def clean_field(value,field,allow_sentinel=False):
    if value is None:return None,0
    if field in JSON_FIELDS:
        parsed=json.loads(value)
        cleaned,count=clean_json_value(parsed)
        return (None if cleaned is None else json.dumps(cleaned,ensure_ascii=False,sort_keys=True,separators=(',',':'))),count
    result,count=clean_text(value,allow_sentinel)
    return result,int(count)


def technology_counts(value):
    if isinstance(value,str):
        return Counter(m.group().casefold().replace(' ','') for m in TECH.finditer(value))
    if isinstance(value,list):
        return sum((technology_counts(item) for item in value),Counter())
    if isinstance(value,dict):
        return sum((technology_counts(item) for item in value.values()),Counter())
    return Counter()


def check_record(row,quality):
    if any(row.get(k)!=quality.get(k) for k in ('record_id','source_id','source_file','snapshot_sha256','source_locator')):
        raise ValueError('Quality flags do not match unified provenance')
    clean={};flags=[];sentinels={};changes={}
    for field in FIELDS:
        original=row.get(field)
        try:out,count=clean_field(original,field, row.get('source_id')=='data_job_analysis' and field=='description_transformed')
        except (ValueError,TypeError):
            out=None;count=0;flags.append('clean_error:'+field)
        clean[field+'_clean']=out
        sentinels[field]=count
        changes[field]=out!=original and not (original is None and out is None)
        if original is not None and out is not None:
            try:
                before=json.loads(original) if field in JSON_FIELDS else original
                after=json.loads(out) if field in JSON_FIELDS else out
            except (ValueError,TypeError):before=after=None
            if isinstance(before,str) and isinstance(after,str):
                # Measured against original text; markup removal can legitimately trigger review.
                if len(before)>=100 and len(after)<len(before)*0.5:flags.append('large_reduction:'+field)
            if technology_counts(before)-technology_counts(after):flags.append('technology_marker_reduced:'+field)
        elif original is not None and out is None and not count:
            flags.append('content_became_empty:'+field)
    return clean,sorted(set(flags)),sentinels,changes


def run():
    src=ROOT/'data/staging/unified_jds.parquet';qpath=ROOT/'data/staging/jd_quality_flags.parquet'
    v=runner.read_json(ROOT/'data/reports/validation_report.json',{})
    source_hash=runner.sha256_file(src);quality_hash=runner.sha256_file(qpath)
    if source_hash!=v.get('input_sha256'):raise ValueError('Quality report does not match unified input')
    table=pq.read_table(src);qtable=pq.read_table(qpath)
    quality=qtable.to_pylist();qmap={x['record_id']:x for x in quality}
    if len(qmap)!=len(quality) or table.num_rows!=len(quality):raise ValueError('Quality record IDs do not match')
    original=table.to_pylist();ids=[x['record_id'] for x in original]
    if len(set(ids))!=len(ids) or set(ids)!=set(qmap):raise ValueError('Missing or duplicate record IDs')
    existing=set(table.column_names);extra={f+'_clean' for f in FIELDS}|{'cleaning_version','cleaning_flags','quality_status','quality_flags'}
    if existing & extra:raise ValueError('Input already contains clean or quality columns')
    cleaned=[];stats=defaultdict(lambda:{'records':0,'changed_records':0,'changed_fields':Counter(),'sentinel_values':Counter(),'flag_records':Counter()})
    for row in original:
        q=qmap[row['record_id']];new,flags,sentinels,changes=check_record(row,q);s=stats[row['source_id']];s['records']+=1
        if any(changes.values()):s['changed_records']+=1
        s['changed_fields'].update({k:1 for k,v in changes.items() if v})
        s['sentinel_values'].update(sentinels);s['flag_records'].update(flags)
        cleaned.append({**new,'cleaning_version':VERSION,'cleaning_flags':flags,'quality_status':q['quality_status'],'quality_flags':q['quality_flags']})
    result=table
    for field in FIELDS:result=result.append_column(field+'_clean',pa.array([r[field+'_clean'] for r in cleaned],type=pa.string()))
    result=result.append_column('cleaning_version',pa.array([VERSION]*len(cleaned),type=pa.string()))
    for field in ('cleaning_flags','quality_flags'):result=result.append_column(field,pa.array([r[field] for r in cleaned],type=pa.list_(pa.string())))
    result=result.append_column('quality_status',pa.array([r['quality_status'] for r in cleaned],type=pa.string()))
    result=result.replace_schema_metadata({**(table.schema.metadata or {}),b'cleaning_version':VERSION.encode(),b'unified_sha256':source_hash.encode(),b'quality_sha256':quality_hash.encode()})
    dest=ROOT/'data/staging/cleaned_jds.parquet';dest.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.cleaned-',suffix='.parquet',dir=dest.parent);os.close(fd)
    try:
        pq.write_table(result,temp,compression='snappy')
        if runner.sha256_file(src)!=source_hash or runner.sha256_file(qpath)!=quality_hash:raise ValueError('Input changed during cleaning')
        if pq.ParquetFile(temp).metadata.num_rows!=len(ids):raise ValueError('Output row count mismatch')
        out_hash=runner.sha256_file(temp);os.replace(temp,dest)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    total=len(ids);overall_changed=sum(s['changed_records'] for s in stats.values())
    report={'generated_at':runner.now(),'cleaning_version':VERSION,'input_sha256':source_hash,'quality_flags_sha256':quality_hash,'output_sha256':out_hash,'total_input_records':total,'total_output_records':result.num_rows,'records_changed':overall_changed,'records_changed_pct':round(100*overall_changed/total,2) if total else 0,'definitions':{'fields':list(FIELDS),'sentinels':sorted(SENTINELS),'sentinel_policy':'whole value only in data_job_analysis.description_transformed, verified in source profile','large_reduction':'original string >= 100 Unicode codepoints and clean length < 50% of original','json_columns':'requirements_clean remains JSON text; string/list/object shape preserved','boilerplate':'exact standalone line click here to apply','no_merge':True},'sources':{sid:{**s,'changed_pct':round(100*s['changed_records']/s['records'],2) if s['records'] else 0} for sid,s in stats.items()}}
    runner.write_json(ROOT/'data/reports/cleaning_report.json',report)
    return report


def main():
    argparse.ArgumentParser(description=__doc__).parse_args();r=run();print(json.dumps({'records':r['total_output_records'],'changed':r['records_changed'],'sources':{k:{'records':v['records'],'changed':v['changed_records'],'flags':dict(v['flag_records']),'sentinels':dict(v['sentinel_values'])} for k,v in r['sources'].items()}},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
