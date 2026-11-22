"""Isolated real registry→ingestion→curated integration; HTTP transport alone is mocked."""
import io,json,shutil,subprocess,sys
from pathlib import Path
import yaml
import pyarrow.parquet as pq
import pytest
from src.collection import runner

ROOT=Path(__file__).resolve().parents[1]

def test_registry_to_curated(tmp_path,monkeypatch):
    for folder in ('src','scripts','configs'):
        shutil.copytree(ROOT/folder,tmp_path/folder,ignore=shutil.ignore_patterns('__pycache__'))
    (tmp_path/'docs').mkdir();(tmp_path/'docs/nguondatagithub.txt').write_text('https://github.com/fixture/jobs\n')
    spec={'path':'vacancies.json','format':'json','title':'vacancy_name','description':'duties_text'}
    source={'source_id':'fixture_jobs','repository':'fixture/jobs','ref':'main','files':[spec]}
    (tmp_path/'configs/sources.yaml').write_text(yaml.safe_dump({'sources':[source]}))
    raw=[{'vacancy_name':'Software Engineer','duties_text':'Responsibilities: '+('Develop software for customers. '*12),'must_know':'Python and SQL experience. '*5,'odd':{'retained':True}}]
    monkeypatch.setattr(runner,'ROOT',tmp_path);monkeypatch.setattr(runner,'DATA',tmp_path/'data')
    monkeypatch.setattr(runner,'revision',lambda *args:('fixture_commit','fixture_blob'))
    monkeypatch.setattr(runner,'request',lambda *args:io.BytesIO(json.dumps(raw).encode()))
    registered=runner.registry();assert registered==[source]
    result=runner.ingest(registered[0],spec,'fixture')
    assert result['status']=='PUBLISHED'
    def cli(*args,ok=True):
        r=subprocess.run([sys.executable,'-m','src.pipeline',*args],cwd=tmp_path,capture_output=True,text=True)
        if ok: assert r.returncode==0,r.stdout+'\n'+r.stderr
        return r
    cli('all','--execute','--version','fixture_v1')
    release=tmp_path/'data/curated/fixture_v1'
    master=pq.read_table(release/'master_jds.parquet').to_pylist()
    assert len(master)==1 and master[0]['source_id']=='fixture_jobs'
    assert json.loads(master[0]['source_extra'])['odd']=={'retained':True}
    before=runner.sha256_file(release/'manifest.json')
    assert 'CACHED' in cli('all','--execute','--version','fixture_v1').stdout
    assert runner.sha256_file(release/'manifest.json')==before
    raw.append({**raw[0], 'vacancy_name':'Cloud Engineer'})
    monkeypatch.setattr(runner,'revision',lambda *args:('fixture_commit_2','fixture_blob_2'))
    assert runner.ingest(registered[0],spec,'fixture2')['status']=='PUBLISHED'
    cli('all','--execute','--resume','--version','fixture_v2')
    assert pq.read_table(tmp_path/'data/curated/fixture_v2/master_jds.parquet').num_rows==2
    assert runner.sha256_file(release/'manifest.json')==before
    pointer=json.loads((tmp_path/'data/raw/fixture_jobs/latest.json').read_text());entry=next(iter(pointer['files'].values()))
    snapshot=tmp_path/'data/raw/fixture_jobs'/entry['snapshot']/'vacancies.json'
    snapshot.write_text('corrupt')
    assert cli('all','--execute','--version','fixture_v3',ok=False).returncode!=0
    assert not (tmp_path/'data/curated/fixture_v3').exists()

@pytest.mark.parametrize('raw',[[],[{'renamed_title':'x','unexpected':'y'}]])
def test_empty_or_changed_schema_does_not_publish(tmp_path,monkeypatch,raw):
    monkeypatch.setattr(runner,'ROOT',tmp_path);monkeypatch.setattr(runner,'DATA',tmp_path/'data')
    monkeypatch.setattr(runner,'revision',lambda *args:('commit','blob'))
    monkeypatch.setattr(runner,'request',lambda *args:io.BytesIO(json.dumps(raw).encode()))
    source={'source_id':'fixture','repository':'fixture/jobs','ref':'main'}
    spec={'path':'jobs.json','format':'json','title':'title','description':'description'}
    assert runner.ingest(source,spec,'fixture')['status']=='QUARANTINED'
    assert not (tmp_path/'data/raw/fixture/latest.json').exists()
