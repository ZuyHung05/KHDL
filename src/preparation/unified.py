"""Map current raw snapshots to a traceable, non-deduplicated JD table."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from src.collection import runner

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / 'data/reports/schema_mapping.csv'
OUTPUT = ROOT / 'data/staging/unified_jds.parquet'
REPORT = ROOT / 'data/reports/unified_mapping_report.json'

# Values with mixed source types are encoded as JSON text, preserving types.
JSON_FIELDS = {'preferred_requirements','education_requirements','language_requirements',
               'certification_requirements','portfolio_requirements','behavioral_traits',
               'benefits','experience_raw','source_level_fields','source_skill_labels',
               'source_role_flags','source_vietnam_flag','source_remote_flag','source_new_flag',
               'requirements'}
NUMBER_FIELDS = {'experience_years_min','experience_years_max'}
DATE_FIELDS = {'posted_at','closing_at','source_created_at','source_updated_at','source_closed_at','source_crawled_at'}
# Retain all contributors as source-name -> original value for many-to-one fields.
MULTI_FIELDS = {'source_skill_labels','source_role_flags','source_level_fields'}
# Priorities are exact source field names, never an implicit CSV order.
PRIORITY = {
 ('data_job_analysis','employment_type'): ['W_Term','W_Term_2','W_Term_3','W_Term_4'],
 ('careersgovsg','source_category'): ['category','field'],
}
METADATA = ['record_id','source_id','source_file','snapshot_sha256','source_locator']


def load_mapping(path=MAPPING):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        entries = list(csv.DictReader(f))
    table = defaultdict(dict)
    for e in entries:
        key = (e['source_id'], e['source_file'])
        field = e['source_field']
        if field in table[key]:
            raise ValueError(f'Duplicate mapping for {key}: {field}')
        table[key][field] = e['unified_field']
    return dict(table)


def missing(value):
    return value is None or (isinstance(value, str) and not value.strip())


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def convert(value, target):
    if missing(value):
        return None
    if target in JSON_FIELDS:
        return encode(value)
    if target in NUMBER_FIELDS:
        if isinstance(value, bool):
            raise ValueError('boolean is not a number')
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('non-finite number')
        return result
    if target in DATE_FIELDS:
        if isinstance(value, (int,float)) and not isinstance(value,bool):
            result = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        elif isinstance(value,str):
            result = datetime.fromisoformat(value.replace('Z','+00:00'))
            if result.tzinfo is None:
                raise ValueError('timestamp lacks timezone')
            result = result.astimezone(timezone.utc)
        else:
            raise ValueError('unsupported timestamp type')
        return result
    if isinstance(value, str):
        return value
    if isinstance(value, (int,float,bool)):
        return str(value)
    raise ValueError('unsupported value type')


def adapt(sid, source_file, checksum, index, raw, mapping, targets):
    if not isinstance(raw, dict):
        raise ValueError('Raw record is not an object')
    locator = {'row_index': index}
    if sid == 'awesome_jobs_vietnam' and raw.get('number') is not None:
        locator['issue_number'] = raw['number']
    identity = encode([sid, source_file, checksum, locator])
    result = {name: None for name in targets}
    result.update(record_id=hashlib.sha256(identity.encode()).hexdigest(), source_id=sid,
                  source_file=source_file, snapshot_sha256=checksum, source_locator=encode(locator))
    groups, extra, errors, unmapped = defaultdict(list), {}, Counter(), Counter()
    for key,value in raw.items():
        target = mapping.get(key, 'source_extra')
        if target == 'source_extra':
            extra[key] = value
            unmapped[key] += 1
        else:
            groups[target].append((key,value))
    for target, values in groups.items():
        if target in MULTI_FIELDS:
            # Keep source field names and untouched values; no inference of flags/skills.
            result[target] = encode(dict(values)) if any(not missing(v) for _,v in values) else None
            continue
        if len(values)>1:
            priorities = PRIORITY.get((sid,target))
            if not priorities or set(k for k,_ in values)-set(priorities):
                raise ValueError(f'No explicit priority for {sid}/{target}')
            values.sort(key=lambda pair:priorities.index(pair[0]))
        selected = False
        for key,value in values:
            if selected:
                extra[key] = value
                continue
            if missing(value):
                if len(values)>1: extra[key] = value
                continue
            try:
                result[target] = convert(value,target)
                selected = True
            except (ValueError, TypeError, OverflowError, OSError):
                errors[key] += 1
                extra[key] = value
                # A conversion failure is not evidence that a lower priority value is equivalent.
                selected = True
    result['source_extra'] = encode(extra) if extra else None
    return result, errors, unmapped


def run(output=OUTPUT, report=REPORT):
    mapping=load_mapping()
    sources=runner.registry()
    registry_ids={s['source_id'] for s in sources}
    rawroot=ROOT/'data/raw'
    unexpected=[p.parent.name for p in rawroot.glob('*/latest.json') if p.parent.name not in registry_ids]
    if unexpected: raise ValueError('Unregistered latest sources: '+', '.join(unexpected))
    targets=sorted({v for fields in mapping.values() for v in fields.values()}-{'source_extra'})
    names=METADATA+targets+['source_extra']
    if len(names)!=len(set(names)): raise ValueError('Mapping conflicts with provenance schema')
    schema=pa.schema([pa.field(name, pa.float64() if name in NUMBER_FIELDS else pa.timestamp('us',tz='UTC') if name in DATE_FIELDS else pa.string(), nullable=name not in METADATA) for name in names], metadata={b'schema_version':b'unified_jd_v1', b'json_columns':','.join(sorted(JSON_FIELDS|{'source_locator','source_extra'})).encode()})
    output,report=Path(output),Path(report)
    output.parent.mkdir(parents=True,exist_ok=True);report.parent.mkdir(parents=True,exist_ok=True)
    fd,tmpname=tempfile.mkstemp(prefix='.unified-',suffix='.parquet',dir=output.parent);os.close(fd)
    counts={}; total=0; checksum_after=[]
    try:
        with pq.ParquetWriter(tmpname,schema,compression='snappy') as writer:
            for source in sources:
                sid=source['source_id']; root=rawroot/sid; pointer=root/'latest.json'
                if not pointer.exists():
                    counts[sid]={'status':'no_latest','input_records':0,'output_records':0};continue
                latest=runner.read_json(pointer,{})
                if not isinstance(latest.get('files'),dict) or not latest['files']:
                    raise ValueError('Missing files in latest: '+sid)
                stats={'status':'ok','input_records':0,'output_records':0,'missing_fields':Counter(),'conversion_errors':Counter(),'unmapped_fields':Counter(),'snapshots':[]}
                for entry in latest['files'].values():
                    pathkey=entry['source_file'];spec=next((f for f in source['files'] if f['path']==pathkey),None)
                    if not spec or (sid,pathkey) not in mapping:raise ValueError('Missing registry/profile mapping: '+sid+'/'+pathkey)
                    path=(root/entry['snapshot']/Path(pathkey).name).resolve()
                    if not path.is_relative_to(root.resolve()) or runner.sha256_file(path)!=entry['file_sha256']:raise ValueError('Invalid snapshot: '+sid+'/'+pathkey)
                    checksum_after.append((path,entry['file_sha256']))
                    stats['snapshots'].append({'source_file':pathkey,'snapshot':entry['snapshot'],'sha256':entry['file_sha256']})
                    batch=[]
                    for idx,raw in enumerate(runner.rows(path,spec)):
                        stats['input_records']+=1
                        obj,errors,unmapped=adapt(sid,pathkey,entry['file_sha256'],idx,raw,mapping[(sid,pathkey)],targets)
                        stats['conversion_errors'].update(errors);stats['unmapped_fields'].update(unmapped)
                        stats['missing_fields'].update(k for k in targets if obj[k] is None)
                        batch.append(obj);stats['output_records']+=1;total+=1
                        if len(batch)>=500:
                            writer.write_table(pa.Table.from_pylist(batch,schema=schema));batch=[]
                    if batch:writer.write_table(pa.Table.from_pylist(batch,schema=schema))
                counts[sid]=stats
        for path,expected in checksum_after:
            if runner.sha256_file(path)!=expected:raise ValueError('Source changed during mapping: '+str(path))
        if pq.ParquetFile(tmpname).metadata.num_rows != total:raise ValueError('Parquet row count mismatch')
        summary={'schema_version':'unified_jd_v1','generated_at':runner.now(),'total_input_records':sum(v['input_records'] for v in counts.values()),'total_output_records':total,'record_id_method':'sha256(JSON [source_id, source_file, snapshot_sha256, source_locator])','source_locator':'zero-based row_index; GitHub issue number when present','json_columns':sorted(JSON_FIELDS|{'source_locator','source_extra'}),'collision_priorities':{f'{s}.{t}':p for (s,t),p in PRIORITY.items()},'sources':counts,'parquet_sha256':runner.sha256_file(tmpname)}
        # Parquet is published only after all sources pass checks; previous output is not touched on failure.
        os.replace(tmpname,output)
        runner.write_json(report,summary)
        return summary
    finally:
        if os.path.exists(tmpname):os.unlink(tmpname)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.parse_args()
    result=run();print(json.dumps({'input':result['total_input_records'],'output':result['total_output_records'],'sources':{k:{'input':v['input_records'],'output':v['output_records'],'conversion_errors':sum(v.get('conversion_errors',{}).values())} for k,v in result['sources'].items()}},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
