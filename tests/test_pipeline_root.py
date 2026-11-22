import pytest
from pathlib import Path
import json
from pathlib import Path
import yaml
from src.preparation.unified import adapt
from src.preparation.eligibility import assess
from src.preparation.eligibility_v2 import assess as v2
from src.pipeline import ROOT,valid

def test_new_schema_explicit_adapter_preserves_provenance(tmp_path):
    raw={'vacancy_name':'Software Engineer','duties_text':'Responsibilities: '+('Build software. '*25),'must_know':'Python and SQL experience required. '*4,'alien_field':{'retain':1}}
    path=tmp_path/'snapshot.json';path.write_text(json.dumps([raw]))
    from src.collection.runner import sha256_file
    mapping=yaml.safe_load((ROOT/'configs/source_adapter_mappings.yaml').read_text())['fixture_jobs']
    record,errors,unmapped=adapt('fixture_jobs','snapshot.json',sha256_file(path),0,raw,mapping,{'job_title','description','requirements'})
    assert not errors and record['snapshot_sha256']==sha256_file(path)
    assert json.loads(record['source_extra'])['alien_field']=={'retain':1}
    clean={**record,'job_title_clean':record['job_title'],'description_clean':record['description'],'requirements_clean':record['requirements']}
    assert assess(clean)[0]=='it' and v2(clean)[1]=='unknown'
    assert not valid('profile',{})

def test_missing_adapter_fails_explicitly(tmp_path,monkeypatch):
    from scripts import profile_raw_schema as profiler
    pointer=tmp_path/'data/raw/unsupported/latest.json';pointer.parent.mkdir(parents=True);pointer.write_text('{"files":{}}')
    monkeypatch.setattr(profiler,'ROOT',tmp_path);monkeypatch.setattr(profiler,'registry',lambda:[])
    import pytest
    with pytest.raises(ValueError,match='Unsupported source schema'):profiler.main()

def test_stage_cache_detects_config_and_output_change(tmp_path,monkeypatch):
    import src.pipeline as p
    monkeypatch.setattr(p,'ROOT',tmp_path)
    monkeypatch.setattr(p,'STAGES',{'one':('module',['config.yaml'],['out.json'])})
    (tmp_path/'config.yaml').write_text('v1');(tmp_path/'out.json').write_text('{}')
    entry={'inputs':p.fingerprint('one'),'outputs':p.outputs('one')}
    assert p.valid('one',entry)
    (tmp_path/'config.yaml').write_text('v2');assert not p.valid('one',entry)
    (tmp_path/'config.yaml').write_text('v1');(tmp_path/'out.json').write_text('corrupted');assert not p.valid('one',entry)

@pytest.mark.skipif(not (ROOT/'data/curated/role_classification/corpora/m02_v1/corpus.jsonl').exists(), reason='Local real-data regression; datasets are intentionally not committed')
def test_m02_corpus_preserves_group_ids_and_preflight():
    import pyarrow.parquet as pq
    from src.classification.runner import preflight
    records=[json.loads(l) for l in (ROOT/'data/curated/role_classification/corpora/m02_v1/corpus.jsonl').open()]
    master=pq.read_table(ROOT/'data/curated/v1/master_jds.parquet',columns=['jd_id','member_count']).to_pylist()
    assert {r['jd_id'] for r in records}=={r['jd_id'] for r in master}
    assert sum(len(r['source_members']) for r in records)==sum(r['member_count'] for r in master)
    assert preflight('m02_v1')['status']=='OFFLINE_OK'

def test_failed_stage_is_not_checkpointed(tmp_path,monkeypatch):
    import src.pipeline as p
    import subprocess
    monkeypatch.setattr(p,'ROOT',tmp_path)
    monkeypatch.setattr(p,'STAGES',{'one':('module',[],['output.json'])})
    def fail(*args,**kwargs): raise subprocess.CalledProcessError(1,'fixture')
    monkeypatch.setattr(p.subprocess,'run',fail)
    state={}
    with pytest.raises(subprocess.CalledProcessError):p.run_stage('one',state,tmp_path/'state.json',True)
    assert state=={} and not (tmp_path/'state.json').exists()
    assert 'FAILED' in (tmp_path/'logs/pipeline.jsonl').read_text()
