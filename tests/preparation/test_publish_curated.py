import json
import shutil
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from src.preparation.publish_curated import select_rows, verify_release, sha, publish

ROOT=Path(__file__).resolve().parents[2]
RELEASE=ROOT/'data/curated/v1'

def test_view_filters_allow_overlap():
    rows=[{'eligibility_status':'eligible','skill_extractable':True},{'eligibility_status':'needs_review','skill_extractable':True},{'eligibility_status':'not_eligible','skill_extractable':True},{'eligibility_status':'needs_review','skill_extractable':False}]
    assert select_rows(rows,'strict_eda')==[0]
    assert select_rows(rows,'skill_candidates')==[0,1,2]
    assert select_rows(rows,'review_pool')==[1,3]
    with pytest.raises(ValueError):select_rows(rows,'invalid')

def test_manifest_detects_tamper(tmp_path):
    p=tmp_path/'sample.parquet'; pq.write_table(pa.table({'id':[1,2]}),p)
    manifest={'files':{'sample.parquet':{'sha256':sha(p),'rows':2}}}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest)); (tmp_path/'manifest.sha256').write_text(sha(tmp_path/'manifest.json')+'  manifest.json\n')
    assert verify_release(tmp_path)==manifest
    p.write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='checksum'): verify_release(tmp_path)

def test_parquet_is_reproducible(tmp_path):
    table=pa.table({'name':['a','b'], 'value':[1,None]}); a=tmp_path/'a.parquet'; b=tmp_path/'b.parquet'
    pq.write_table(table,a);pq.write_table(table,b)
    assert sha(a)==sha(b)

@pytest.mark.skipif(not RELEASE.exists(),reason='Release is not yet available')
def test_release_integrity_and_exact_views():
    manifest=verify_release(RELEASE); master=pq.read_table(RELEASE/'master_jds.parquet'); rows=master.to_pylist(); mapping=pq.read_table(RELEASE/'duplicate_mapping.parquet').to_pylist()
    assert len(rows)==manifest['files']['master_jds.parquet']['rows']
    assert len({r['record_id'] for r in mapping})==len(mapping)
    assert {r['representative_record_id'] for r in mapping}=={r['record_id'] for r in rows}
    for view in ('strict_eda','skill_candidates','review_pool'):
        actual=pq.read_table(RELEASE/(view+'.parquet'))
        expected=master.take(pa.array(select_rows(rows,view),type=pa.int64()))
        assert actual.equals(expected,check_metadata=True)
    assert sum(r['member_count'] for r in rows)==len(mapping)

@pytest.mark.skipif(not RELEASE.exists(),reason='Release is not yet available')
def test_existing_release_never_overwritten(tmp_path):
    curated=tmp_path/'data/curated';curated.mkdir(parents=True);shutil.copytree(RELEASE,curated/'v1')
    st=tmp_path/'data/staging';st.mkdir(parents=True)
    shutil.copyfile(ROOT/'data/staging/eligible_jds_v2.parquet',st/'eligible_jds_v2.parquet')
    shutil.copyfile(ROOT/'data/staging/duplicate_mapping.parquet',st/'duplicate_mapping.parquet')
    before={p.name:sha(p) for p in (curated/'v1').iterdir()}
    publish(tmp_path)
    assert before=={p.name:sha(p) for p in (curated/'v1').iterdir()}
    (st/'eligible_jds_v2.parquet').write_bytes(b'different')
    with pytest.raises(ValueError,match='Existing release differs'):publish(tmp_path)
    assert before=={p.name:sha(p) for p in (curated/'v1').iterdir()}

@pytest.mark.skipif(not RELEASE.exists(),reason='Release is not yet available')
def test_audit_is_read_only_and_recomputes_eligibility():
    from src.preparation.publish_curated import audit
    manifest=verify_release(RELEASE)
    paths=list((ROOT/'data/staging').glob('*.parquet'))
    for item in manifest['raw_snapshots']:
        paths.append(ROOT/'data/raw'/item['source_id']/item['snapshot']/Path(item['source_file']).name)
    before={str(p):sha(p) for p in paths}
    master,mapping,rows,stats,hashes,_=audit(ROOT)
    assert len(rows)==master.num_rows and mapping.num_rows==stats['counts']['raw_records']
    assert before=={str(p):sha(p) for p in paths}

@pytest.mark.skipif(not RELEASE.exists(),reason='Release is not yet available')
def test_rebuild_release_artifact_bytes(tmp_path):
    manifest=verify_release(RELEASE)
    master=pq.read_table(ROOT/'data/staging/eligible_jds_v2.parquet'); rows=master.to_pylist()
    for name,table in [('master_jds.parquet',master),('duplicate_mapping.parquet',pq.read_table(ROOT/'data/staging/duplicate_mapping.parquet'))]+[(view+'.parquet',master.take(pa.array(select_rows(rows,view),type=pa.int64()))) for view in ('strict_eda','skill_candidates','review_pool')]:
        path=tmp_path/name;pq.write_table(table,path)
        assert sha(path)==manifest['files'][name]['sha256']
