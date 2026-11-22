"""Root CLI. Offline by default; stage fingerprints and output integrity control reuse."""
import argparse,json,subprocess,sys,hashlib
from pathlib import Path
from src.collection.runner import sha256_file
ROOT=Path(__file__).resolve().parents[1]
STAGES={
 'profile':('scripts.profile_raw_schema',['configs/sources.yaml','scripts/profile_raw_schema.py','configs/source_adapter_mappings.yaml','src/collection/runner.py'],['data/reports/schema_profile.json','data/reports/schema_mapping.csv']),
 'unified':('src.preparation.unified',['src/preparation/unified.py'],['data/staging/unified_jds.parquet','data/reports/unified_mapping_report.json']),
 'quality':('src.preparation.quality',['src/preparation/quality.py'],['data/staging/jd_quality_flags.parquet','data/reports/validation_report.json','data/reports/missing_values_report.csv']),
 'clean':('src.preparation.cleaning',['src/preparation/cleaning.py'],['data/staging/cleaned_jds.parquet','data/reports/cleaning_report.json']),
 'dedup':('src.preparation.dedup_stage',['src/preparation/deduplicate.py','src/preparation/audit_reconciliation.py','src/preparation/dedup_stage.py'],['data/staging/deduplicated_jds.parquet','data/staging/duplicate_mapping.parquet','data/reports/dedup_report.json','data/reports/dedup_reconciliation_report.json']),
 'normalize':('src.preparation.normalize',['src/preparation/normalize.py','configs/field_normalization.yaml'],['data/staging/normalized_jds.parquet','data/reports/normalization_report.json']),
 'eligibility':('src.preparation.eligibility',['src/preparation/eligibility.py'],['data/staging/eligible_jds.parquet','data/reports/eligibility_report.json']),
 'eligibility-v2':('src.preparation.eligibility_v2',['src/preparation/eligibility_v2.py'],['data/staging/eligible_jds_v2.parquet','data/reports/eligibility_v2_report.json']),
}
def digest(paths):
 return {str(p.relative_to(ROOT)):sha256_file(p) for p in sorted(set(paths)) if p.is_file()}
def fingerprint(stage):
 names=list(STAGES);i=names.index(stage)
 paths=list((ROOT/'data/raw').glob('*/latest.json'))
 for name in names[:i+1]:paths += [ROOT/p for p in STAGES[name][1]]
 if i: paths += [ROOT/p for p in STAGES[names[i-1]][2]]
 # Snapshot bytes, not just pointers: corrupt inputs invalidate even unchanged latest.json.
 for pointer in (ROOT/'data/raw').glob('*/latest.json'):
  for e in json.loads(pointer.read_text())['files'].values():paths.append(pointer.parent/e['snapshot']/Path(e['source_file']).name)
 return digest(paths)
def outputs(stage):return digest([ROOT/p for p in STAGES[stage][2]])
def valid(stage,entry):return entry.get('inputs')==fingerprint(stage) and entry.get('outputs')==outputs(stage) and len(outputs(stage))==len(STAGES[stage][2])
def save_state(path, state):
 path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(state,indent=2));temp.replace(path)

def event(stage,status,**details):
 from datetime import datetime,timezone
 path=ROOT/'logs/pipeline.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('a') as f:f.write(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),'stage':stage,'status':status,**details})+'\n')

def validate_stage(stage):
 import pyarrow.parquet as pq
 for name in STAGES[stage][2]:
  path=ROOT/name
  if not path.is_file():raise ValueError('Missing output: '+name)
  if path.suffix=='.parquet' and pq.read_metadata(path).num_rows==0:raise ValueError('Empty output: '+name)
 pairs={'unified':('unified_mapping_report.json','parquet_sha256','unified_jds.parquet'),
 'clean':('cleaning_report.json','output_sha256','cleaned_jds.parquet'),
 'normalize':('normalization_report.json','output_sha256','normalized_jds.parquet'),
 'eligibility':('eligibility_report.json','output_sha256','eligible_jds.parquet'),
 'eligibility-v2':('eligibility_v2_report.json','output_sha256','eligible_jds_v2.parquet')}
 if stage in pairs:
  report,key,file=pairs[stage]
  if json.loads((ROOT/'data/reports'/report).read_text())[key]!=sha256_file(ROOT/'data/staging'/file):raise ValueError('Output report checksum mismatch: '+stage)

def run_stage(name,state,path,execute):
 cached=valid(name,state.get(name,{}))
 print(json.dumps({'stage':name,'status':'CACHED' if cached else 'STALE','execute':execute}),flush=True)
 if cached or not execute:return
 event(name,'RUNNING')
 try:
  inputs=fingerprint(name)
  subprocess.run([sys.executable,'-m',STAGES[name][0]],cwd=ROOT,check=True)
  validate_stage(name)
  if inputs!=fingerprint(name):raise ValueError('Inputs changed during stage: '+name)
  state[name]={'inputs':inputs,'outputs':outputs(name)};save_state(path,state);event(name,'COMPLETED')
 except Exception as error:
  event(name,'FAILED',error_type=type(error).__name__);raise

def main():
 import fcntl
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('stage',choices=['all','status','adopt','ingest','gemini','publish','reconcile','corpus']+list(STAGES))
 p.add_argument('--execute',action='store_true');p.add_argument('--resume',action='store_true',help='Reuse validated stage checkpoints (also default)')
 p.add_argument('--version',default='v1');p.add_argument('--source');p.add_argument('--corpus',default='roles_v8')
 p.add_argument('--with-ingest',action='store_true',help='Explicitly include network ingestion in all')
 p.add_argument('--prepare-corpus',action='store_true',help='After publishing freeze and preflight the named M02 corpus; no API')
 a=p.parse_args();statepath=ROOT/'data/pipeline_state.json'
 (ROOT/'data').mkdir(exist_ok=True)
 with (ROOT/'data/.pipeline.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  state=json.loads(statepath.read_text()) if statepath.exists() else {}
  execute=a.execute and a.stage!='status'
  if a.stage=='adopt':
   from src.preparation.publish_curated import audit
   audit(ROOT)
   for name in STAGES:state[name]={'inputs':fingerprint(name),'outputs':outputs(name)}
   save_state(statepath,state);print('Verified existing M02 artifacts adopted.');return
  if a.stage=='ingest' or (a.stage=='all' and a.with_ingest):
   cmd=[sys.executable,'-m','src.collection.runner','--mode','update']
   if a.source:cmd+=['--source',a.source]
   if not execute:cmd+=['--dry-run']
   subprocess.run(cmd,cwd=ROOT,check=True)
   if a.stage=='ingest':return
  if a.stage=='gemini':
   subprocess.run([sys.executable,'-m','src.classification.runner','preflight','--corpus',a.corpus,'--dry-run'],cwd=ROOT,check=True);return
  if a.stage=='reconcile':
   if execute:
    from src.classification.reconcile import run
    run()
   else:print('Plan: provenance/input/version reconciliation; --execute writes separate artifact')
   return
  if a.stage=='corpus':
   if execute:
    from src.classification.curated_corpus import prepare
    prepare(a.corpus,a.version)
   else:print('Plan: freeze M02 corpus; --execute required')
   return
  names=list(STAGES) if a.stage in ('all','status') else list(STAGES)[:list(STAGES).index(a.stage)+1] if a.stage in STAGES else []
  for name in names:run_stage(name,state,statepath,execute)
  if a.stage in ('all','publish') and execute:
   from src.preparation.publish_curated import publish
   publish(ROOT,a.version)
   if a.prepare_corpus:
    from src.classification.curated_corpus import prepare
    from src.classification.runner import preflight
    dest=ROOT/'data/curated/role_classification/corpora'/a.corpus
    if not dest.exists():prepare(a.corpus,a.version)
    else:
     manifest=json.loads((dest/'corpus_manifest.json').read_text())
     if manifest.get('m02_manifest_sha256')!=sha256_file(ROOT/'data/curated'/a.version/'manifest.json'):raise ValueError('Existing corpus uses another release')
    print(json.dumps(preflight(a.corpus)))
if __name__=='__main__':main()
