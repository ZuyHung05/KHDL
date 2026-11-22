"""Audit and atomically publish an immutable, reproducible M02 release."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, tempfile
from collections import Counter
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from src.preparation.eligibility import sha, assess as assess_v1
from src.preparation.eligibility_v2 import assess as assess_v2

VERSION='m02_curated_v1'
FILTERS={'strict_eda':'eligibility_status == eligible','skill_candidates':'skill_extractable == true','review_pool':'eligibility_status == needs_review'}
REPORTS=['schema_profile','unified_mapping_report','validation_report','cleaning_report','cleaning_qa_report','cleaning_qa_audit','dedup_report','dedup_reconciliation_report','normalization_report','eligibility_report','eligibility_v2_report','eligibility_v2_audit']

def jread(p): return json.loads(p.read_text(encoding='utf8'))
def write_json(p,obj): p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf8')
def require(ok,message):
    if not ok: raise ValueError(message)

def select_rows(rows,name):
    if name=='strict_eda': return [i for i,r in enumerate(rows) if r['eligibility_status']=='eligible']
    if name=='skill_candidates': return [i for i,r in enumerate(rows) if r['skill_extractable'] is True]
    if name=='review_pool': return [i for i,r in enumerate(rows) if r['eligibility_status']=='needs_review']
    raise ValueError('Unknown view')

def verify_release(folder):
    m=jread(folder/'manifest.json'); require(sha(folder/'manifest.json')==(folder/'manifest.sha256').read_text().split()[0], 'Manifest checksum mismatch')
    for name,entry in m['files'].items():
        p=folder/name; require(p.is_file() and sha(p)==entry['sha256'], 'Published file checksum mismatch: '+name)
        if name.endswith('.parquet'): require(pq.read_metadata(p).num_rows==entry['rows'], 'Published row count mismatch: '+name)
    return m

def audit(root):
    st=root/'data/staging'; reports=root/'data/reports'; rr={name:jread(reports/(name+'.json')) for name in REPORTS if name != 'eligibility_v2_audit' or (reports/(name+'.json')).exists()}
    paths={'unified':st/'unified_jds.parquet','quality':st/'jd_quality_flags.parquet','cleaned':st/'cleaned_jds.parquet','dedup':st/'deduplicated_jds.parquet','mapping':st/'duplicate_mapping.parquet','normalized':st/'normalized_jds.parquet','v1':st/'eligible_jds.parquet','v2':st/'eligible_jds_v2.parquet'}
    hashes={k:sha(p) for k,p in paths.items()}
    checks={'unified_report':hashes['unified']==rr['unified_mapping_report']['parquet_sha256'], 'validation_input':hashes['unified']==rr['validation_report']['input_sha256'], 'cleaning_input':hashes['unified']==rr['cleaning_report']['input_sha256'], 'cleaning_quality':hashes['quality']==rr['cleaning_report']['quality_flags_sha256'], 'cleaning_output':hashes['cleaned']==rr['cleaning_report']['output_sha256'], 'dedup_input':hashes['cleaned']==rr['dedup_report']['input_sha256']==rr['dedup_reconciliation_report']['input_sha256'], 'normalization_input':hashes['dedup']==rr['normalization_report']['input_sha256'], 'normalization_mapping':hashes['mapping']==rr['normalization_report']['mapping_sha256'], 'normalization_output':hashes['normalized']==rr['normalization_report']['output_sha256'], 'eligibility_v1_input':hashes['normalized']==rr['eligibility_report']['input_sha256'], 'eligibility_v1_output':hashes['v1']==rr['eligibility_report']['output_sha256'], 'eligibility_v2_input':hashes['v1']==rr['eligibility_v2_report']['v1_sha256'] and hashes['normalized']==rr['eligibility_v2_report']['normalized_sha256'], 'eligibility_v2_mapping':hashes['mapping']==rr['eligibility_v2_report']['mapping_sha256'], 'eligibility_v2_output':hashes['v2']==rr['eligibility_v2_report']['output_sha256']}
    require(all(checks.values()),'Checksum chain failed: '+str([k for k,v in checks.items() if not v]))
    # Snapshot input is the exact pointer set used at unified ingestion, not a source-name inference.
    raw=[]
    for sid,stats in rr['unified_mapping_report']['sources'].items():
        source=root/'data/raw'/sid; pointer=jread(source/'latest.json'); current={(e['source_file'],e['snapshot'],e['file_sha256']) for e in pointer['files'].values()}; recorded={(e['source_file'],e['snapshot'],e['sha256']) for e in stats['snapshots']}
        require(current==recorded, 'Latest snapshot changed: '+sid)
        for file,snapshot,digest in sorted(recorded):
            p=(source/snapshot/Path(file).name).resolve(); require(p.is_relative_to(source.resolve()) and p.is_file() and sha(p)==digest,'Raw snapshot mismatch: '+sid+'/'+file)
            raw.append({'source_id':sid,'source_file':file,'snapshot':snapshot,'sha256':digest})
    tables={k:pq.read_table(p) for k,p in paths.items()}; master=tables['v2']; rows=master.to_pylist(); maps=tables['mapping'].to_pylist(); unified=tables['unified'].to_pylist()
    nraw=rr['unified_mapping_report']['total_output_records']; ngroups=rr['dedup_report']['output_jds']
    require(nraw==len(unified)==len(maps)==tables['quality'].num_rows==tables['cleaned'].num_rows,'Raw record count mismatch')
    require(ngroups==len(rows)==tables['dedup'].num_rows==tables['normalized'].num_rows==tables['v1'].num_rows,'Group count mismatch')
    require(nraw==rr['schema_profile']['total_raw_records'] and nraw-ngroups==rr['dedup_report']['merged_records'],'Pipeline count mismatch')
    raw_by_id={r['record_id']:r for r in unified}; reps={r['record_id']:r for r in rows}
    require(len(raw_by_id)==nraw and len(reps)==ngroups and len({m['record_id'] for m in maps})==nraw,'Duplicate IDs')
    grouped=Counter(); members={k:{x['record_id'] for x in json.loads(r['members_json'])} for k,r in reps.items()}
    for m in maps:
        r=raw_by_id.get(m['record_id']); rep=reps.get(m['representative_record_id']); require(r is not None and rep is not None,'Mapping target missing')
        require(all(m[k]==r[k] for k in ('source_id','source_file','snapshot_sha256','source_locator')) and m['jd_id']==rep['jd_id'] and m['record_id'] in members[rep['record_id']],'Provenance mismatch')
        grouped[rep['record_id']]+=1
    require(all(grouped[k]==r['member_count']==len(members[k]) for k,r in reps.items()),'Cluster member count mismatch')
    # Recompute both stages as an independent repeatability check; input artifacts remain untouched.
    normrows=tables['normalized'].to_pylist(); v1rows=tables['v1'].to_pylist(); fields=['domain_status','geography_status','content_status','eligibility_status','eligibility_reason_codes','eligibility_evidence']
    for nr,one,two in zip(normrows,v1rows,rows):
        require(nr['record_id']==one['record_id']==two['record_id'],'Order mismatch')
        require(tuple(one[f] for f in fields)==assess_v1(nr),'V1 recomputation mismatch')
        require(tuple(two[f] for f in fields)+ (two['skill_extractable'],)==assess_v2(one),'V2 recomputation mismatch')
    require(sha(root/'src/preparation/eligibility.py')==rr['eligibility_report']['rules_sha256'] and sha(root/'src/preparation/eligibility_v2.py')==rr['eligibility_v2_report']['rules_sha256'],'Eligibility rules changed since run')
    missing={}
    for f in ('job_title_clean','description_clean','requirements_clean','raw_job_text_clean','description_transformed_clean','country_normalized','location_normalized','seniority_normalized','posted_at_normalized'):
        absent=sum(r.get(f) is None or r.get(f)=='' or r.get(f)==[] for r in rows); missing[f]={'missing_or_empty':absent,'rate':round(absent/len(rows),6)}
    stats={'counts':{'raw_records':nraw,'groups':ngroups,'raw_by_source':dict(Counter(r['source_id'] for r in unified)),'groups_by_source':dict(Counter(r['source_id'] for r in rows))},'chain_checks':checks,'raw_snapshots':raw,'missing_representatives':missing,'validation_quality_counts_raw':rr['validation_report']['status_counts'],'cleaning':{'records_changed':rr['cleaning_report']['records_changed'],'large_reduction_count':rr['cleaning_qa_report']['large_reduction_count'],'original_qa_findings':rr['cleaning_qa_report']['finding_counts'],'reconciliation_findings':rr['dedup_reconciliation_report']['cleaning_audit_counts']},'dedup':{k:rr['dedup_report'][k] for k in ('duplicate_clusters','merged_records','near_candidates','legacy_gemini')},'normalization_coverage_by_source':rr['normalization_report']['coverage_by_source'],'eligibility_v2':rr['eligibility_v2_report']['v2_totals'],'eligibility_by_source':rr['eligibility_v2_report']['by_source'],'warnings':['Views overlap and are selected by rules, not gold labels.','Strict EDA excludes unknown, partial, transformed and unstructured items and has source, geography and occupation selection bias.','Missing or unmapped geography, seniority and posting dates limit market conclusions.','Skill candidates are not restricted to IT or Vietnam; skill flag is a heuristic.','GitHub issues may contain multiple positions; transformed text is not a full JD.','Gemini roles_v8 labels were not joined; legacy dedup IDs are not equivalent to M02 groups.','The small eligibility audit is not independent or a gold standard.']}
    return master,tables['mapping'],rows,stats,hashes,rr

def publish(root,version='v1'):
    require(version and version not in ('.','..') and '/' not in version and '\\' not in version,'Invalid release version')
    root=Path(root).resolve(); curated=root/'data/curated'; final=curated/version; curated.mkdir(parents=True,exist_ok=True)
    if final.exists():
        manifest=verify_release(final)
        require(manifest['release_version']==VERSION and manifest['inputs']['v2']==sha(root/'data/staging/eligible_jds_v2.parquet') and manifest['inputs']['mapping']==sha(root/'data/staging/duplicate_mapping.parquet'),'Existing release differs; choose a new release version')
        print('Existing immutable release verified; no files changed.'); return manifest
    master,mapping,rows,stats,hashes,rr=audit(root)
    lock=curated/('.'+version+'.publish.lock'); fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd); tmp=None
    try:
        require(not final.exists(),'Release already exists'); tmp=Path(tempfile.mkdtemp(prefix='.'+version+'-',dir=curated)); files={}
        schema=[{'name':f.name,'type':str(f.type),'nullable':f.nullable} for f in master.schema]
        for name,table in [('master_jds.parquet',master),('duplicate_mapping.parquet',mapping)]+[(name+'.parquet',master.take(pa.array(select_rows(rows,name),type=pa.int64()))) for name in FILTERS]:
            pq.write_table(table,tmp/name); files[name]={'sha256':sha(tmp/name),'rows':table.num_rows,'by_source':dict(Counter(table.column('source_id').to_pylist()))}
        view_ids={name:{rows[i]['record_id'] for i in select_rows(rows,name)} for name in FILTERS}
        stats['views']={name:{**files[name+'.parquet'],'filter':FILTERS[name]} for name in FILTERS}
        stats['view_overlaps']={a+' & '+b:len(view_ids[a]&view_ids[b]) for i,a in enumerate(FILTERS) for b in list(FILTERS)[i+1:]}
        write_json(tmp/'quality_report.json',stats);files['quality_report.json']={'sha256':sha(tmp/'quality_report.json')}
        schema_hash=hashlib.sha256(json.dumps(schema,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        manifest={'release_version':VERSION,'directory_version':version,'inputs':hashes,'input_reports_sha256':{name:sha(root/'data/reports'/(name+'.json')) for name in rr},'raw_snapshots':stats['raw_snapshots'],'schema':schema,'schema_sha256':schema_hash,'filters':FILTERS,'files':files,'builder_sha256':sha(Path(__file__)),'notes':['Immutable release: never overwrite; publish a different version for changes.','Membership and source counts refer to deduplicated representative groups.','No Gemini labels joined.']}
        write_json(tmp/'manifest.json',manifest); (tmp/'manifest.sha256').write_text(sha(tmp/'manifest.json')+'  manifest.json\n')
        verify_release(tmp)
        require(all(sha(root/'data/staging'/paths)==hashes[key] for key,paths in {'unified':'unified_jds.parquet','quality':'jd_quality_flags.parquet','cleaned':'cleaned_jds.parquet','dedup':'deduplicated_jds.parquet','mapping':'duplicate_mapping.parquet','normalized':'normalized_jds.parquet','v1':'eligible_jds.parquet','v2':'eligible_jds_v2.parquet'}.items()),'Staging changed during publication')
        os.rename(tmp,final); tmp=None
        # A mutable convenience copy; the release itself contains the immutable report.
        write_json(root/'data/reports/final_quality_report.json',stats)
        print(json.dumps({'release':str(final),'files':files,'view_overlaps':stats['view_overlaps']},ensure_ascii=False,indent=2));return manifest
    finally:
        if tmp is not None: shutil.rmtree(tmp)
        lock.unlink(missing_ok=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--version',default='v1');a=p.parse_args();publish(a.root,a.version)
