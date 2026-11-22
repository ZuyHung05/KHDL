import pytest
from pathlib import Path
import json
from datetime import timezone
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from src.preparation import unified


def test_multiple_fields_and_unmapped_preserved():
    mapping={'W_Term':'employment_type','W_Term_2':'employment_type','foo':'source_extra'}
    row={'W_Term':'Full-time','W_Term_2':'Contract','foo':{'x':1}}
    out,err,unknown=unified.adapt('data_job_analysis','x.csv','a'*64,7,row,mapping,['employment_type'])
    assert out['employment_type']=='Full-time'
    assert json.loads(out['source_extra'])=={'W_Term_2':'Contract','foo':{'x':1}}
    assert json.loads(out['source_locator'])=={'row_index':7}
    assert unknown=={'foo':1} and not err
    assert out['record_id']==unified.adapt('data_job_analysis','x.csv','a'*64,7,row,mapping,['employment_type'])[0]['record_id']
    assert out['record_id']!=unified.adapt('data_job_analysis','x.csv','a'*64,8,row,mapping,['employment_type'])[0]['record_id']


def test_no_raw_description_inference_and_mixed_values():
    row={'raw job':'full original JD','must_have_requirements':['Python','SQL'],'unused':42}
    mapping={'raw job':'raw_job_text','must_have_requirements':'requirements'}
    out,err,unmapped=unified.adapt('dpl_evaluation','x','b'*64,0,row,mapping,['description','raw_job_text','requirements'])
    assert out['description'] is None and out['raw_job_text']=='full original JD'
    assert json.loads(out['requirements'])==['Python','SQL']
    assert json.loads(out['source_extra'])=={'unused':42} and not err
    assert unmapped=={'unused':1}


def test_conversion_failure_preserves_raw_and_never_infers_timezone():
    row={'Min_YOE':'unknown','crawled_at':'2024-01-01 12:00:00'}
    mapping={'Min_YOE':'experience_years_min','crawled_at':'source_crawled_at'}
    out,errors,_=unified.adapt('example','x','c'*64,1,row,mapping,['experience_years_min','source_crawled_at'])
    assert out['experience_years_min'] is None and out['source_crawled_at'] is None
    assert json.loads(out['source_extra'])==row and errors=={'Min_YOE':1,'crawled_at':1}
    assert unified.convert(0,'posted_at').tzinfo==timezone.utc
    assert unified.convert('', 'experience_years_min') is None


def test_unexpected_collision_fails():
    with pytest.raises(ValueError,match='No explicit priority'):
        unified.adapt('example','x','d'*64,0,{'a':'one','b':'two'},{'a':'job_title','b':'job_title'},['job_title'])


@pytest.mark.skipif(not (unified.ROOT/'data/staging/unified_jds.parquet').exists(), reason='Local real-data regression; datasets are intentionally not committed')
def test_published_data_reconciles():
    profile=json.loads((unified.ROOT/'data/reports/schema_profile.json').read_text())
    path=unified.OUTPUT
    if not path.exists():pytest.skip('Run the preparation command first')
    table=pq.read_table(path,columns=['record_id','source_id','source_file','snapshot_sha256','source_locator'])
    assert table.num_rows==profile['total_raw_records']
    assert len(set(table['record_id'].to_pylist()))==table.num_rows
    assert all(all(x is not None for x in row.values()) for row in table.to_pylist())
