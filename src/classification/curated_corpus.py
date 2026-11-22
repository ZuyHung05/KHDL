"""Freeze a new Gemini corpus using M02 group IDs and exact member provenance."""
import argparse,json,re,tempfile,shutil
from collections import Counter
import pyarrow.parquet as pq
import yaml
from .dataset import ROOT,OUT,payload,content_hash,sample_candidates
from .rules import classify
from src.collection.runner import sha256_file,write_json
from src.preparation.publish_curated import verify_release

def prepare(corpus_id,release='v1'):
 if not re.fullmatch(r'[A-Za-z0-9_-]+',corpus_id) or not re.fullmatch(r'[A-Za-z0-9_-]+',release):raise ValueError('Invalid corpus or release ID')
 dest=OUT/corpus_id
 if dest.exists():raise FileExistsError('Frozen corpus already exists')
 base=ROOT/'data/curated'/release;manifest=verify_release(base);taxpath=ROOT/'configs/role_taxonomy.yaml';taxonomy=yaml.safe_load(taxpath.read_text());records=[];snapshots=[]
 for row in pq.read_table(base/'master_jds.parquet').to_pylist():
  members=[]
  for m in json.loads(row['members_json']):
   loc=json.loads(m['source_locator']);members.append({'source_id':m['source_id'],'file':m['source_file'],'sha256':m['snapshot_sha256'],'row_index':loc['row_index'],'issue_number':loc.get('issue_number')})
  status,family,role=classify(row.get('job_title_clean') or '',taxonomy)
  record={'jd_id':row['jd_id'],'title':row.get('job_title_clean') or '', 'description':row.get('description_clean') or '', 'requirements':row.get('requirements_clean') or '', 'source_members':members,'rule_status':status,'rule_family':family,'rule_primary_role':role,'preprocessing_version':'nfc_redact_v6','m02_record_id':row['record_id'],'input_policy':'separate cleaned description/requirements; no transformed or issue fallback'}
  record['content_hash']=content_hash(payload(record));records.append(record)
 for snap in manifest['raw_snapshots']:
  snapshots.append({'source_id':snap['source_id'],'source_file':snap['source_file'],'snapshot':snap['snapshot'],'file_sha256':snap['sha256']})
 candidates=[r for r in records if r['rule_status'] in ('unknown','needs_review')];OUT.mkdir(parents=True,exist_ok=True);tmp=__import__('pathlib').Path(tempfile.mkdtemp(prefix='.m02-',dir=OUT))
 try:
  for name,items in [('corpus.jsonl',records),('candidates.jsonl',candidates)]:
   with (tmp/name).open('w') as f:
    for item in items:f.write(json.dumps(item,ensure_ascii=False)+'\n')
  write_json(tmp/'samples.json',sample_candidates(candidates))
  write_json(tmp/'corpus_manifest.json',{'corpus_id':corpus_id,'total':len(records),'counts':{s:sum(r['rule_status']==s for r in records) for s in ('classified','unknown','needs_review')},'taxonomy_sha256':sha256_file(taxpath),'snapshots':snapshots,'preprocessing_version':'nfc_redact_v6','dedup_version':'dedup_v2','m02_manifest_sha256':sha256_file(base/'manifest.json'),'input_policy':'description_clean and requirements_clean only','artifacts_sha256':{name:sha256_file(tmp/name) for name in ('corpus.jsonl','candidates.jsonl','samples.json')}})
  tmp.rename(dest)
 finally:
  if tmp.exists():shutil.rmtree(tmp)
 print(json.dumps({'corpus':corpus_id,'records':len(records),'candidates':len(candidates)}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--corpus-id',required=True);p.add_argument('--release',default='v1');a=p.parse_args();prepare(a.corpus_id,a.release)
