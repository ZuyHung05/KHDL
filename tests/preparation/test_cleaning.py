import pytest
from pathlib import Path
import json
import pyarrow.parquet as pq
from src.preparation.cleaning import clean_text, clean_field, check_record, FIELDS


def test_html_markdown_entities_and_technology():
    text='<h2>Requirements</h2><ul><li>C++ and C#</li><li>.NET, Node.js, CI/CD, AWS EC2</li></ul><p>3 years &amp; more</p>'
    clean,_=clean_text(text)
    assert '## Requirements' in clean and '- C++ and C#' in clean
    assert all(x in clean for x in ('C++','C#','.NET','Node.js','CI/CD','AWS EC2','3 years','& more'))
    assert clean_text(clean)[0]==clean


def test_sentinel_context_and_non_substring():
    assert clean_text(' NA ',True)==(None,True)
    assert clean_text(' NA ',False)[0]=='NA'
    assert clean_text('Experience with NA region and null values',True)[0]=='Experience with NA region and null values'
    assert clean_text('N/A role',True)[0]=='N/A role'


def test_nested_json_requirements_and_nonmerge():
    value=json.dumps(['C++ &amp; CI/CD','NA'])
    out,count=clean_field(value,'requirements')
    assert json.loads(out)==['C++ & CI/CD','NA'] and count==0
    assert clean_field(out,'requirements')[0]==out
    base={'record_id':'1','source_id':'test','source_file':'a','snapshot_sha256':'x','source_locator':'{}','job_title':'Dev','description':None,'raw_job_text':'<p>Build API</p>','requirements':None,'description_transformed':None,'responsibilities':None}
    q={k:base[k] for k in ('record_id','source_id','source_file','snapshot_sha256','source_locator')}
    clean,_,_,_=check_record(base,q)
    assert clean['description_clean'] is None and clean['raw_job_text_clean']=='Build API'


def test_unicode_whitespace_and_markup_preserves_unknown_tags():
    value='e\u0301\x00  <T>  [Role](https://example.com)\n\n\n- Item'
    result,_=clean_text(value)
    assert 'é' in result and '<T>' in result and 'Role (https://example.com)' in result and '- Item' in result
    assert clean_text(result)[0]==result


@pytest.mark.skipif(not Path('data/staging/cleaned_jds.parquet').exists(), reason='Local real-data regression; datasets are intentionally not committed')
def test_current_output_preserves_original_and_is_idempotent():
    before=pq.read_table('data/staging/unified_jds.parquet')
    after=pq.read_table('data/staging/cleaned_jds.parquet')
    assert before.num_rows==after.num_rows==9868
    for name in before.column_names:
        assert before[name].equals(after[name])
    for row in after.select(['source_id']+[f+'_clean' for f in FIELDS]).to_pylist():
        for field in FIELDS:
            value=row[field+'_clean']
            assert clean_field(value,field,row['source_id']=='data_job_analysis' and field=='description_transformed')[0]==value
