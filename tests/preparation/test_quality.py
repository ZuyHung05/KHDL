import json
from src.preparation import quality, unified


def sample(**kw):
    return {'source_id':'example','job_title':'Cloud Engineer','description':'A'*120,'requirements':None,'raw_job_text':None,'description_transformed':None,**kw}


def test_status_rule_and_optional_fields():
    assert quality.judge(sample()) == ('usable',[])
    assert quality.judge(sample(description=None,requirements=json.dumps(['Build pipelines']))) == ('needs_review',['requirements_only'])
    assert quality.judge(sample(description=None,description_transformed='Translated')) == ('needs_review',['transformed_text_only'])
    assert quality.judge(sample(description=None)) == ('unusable',['no_job_content'])
    assert quality.judge(sample(job_title='',description='A'*120))[0] == 'needs_review'
    assert quality.judge(sample(description='short')) == ('needs_review',['short_description'])
    assert quality.judge(sample(source_id='awesome_jobs_vietnam',description=None,raw_job_text='A'*120))[0] == 'needs_review'


def test_missing_distinguishes_unavailable_and_null():
    assert quality.raw_state({},[]) == 'not_provided'
    assert quality.raw_state({},['a']) == 'missing'
    assert quality.raw_state({'a':None},['a']) == 'null'
    assert quality.raw_state({'a':'  '},['a']) == 'empty'
    assert quality.raw_state({'a':'N/A'},['a']) == 'sentinel'
    assert quality.raw_state({'a':'N/A','b':'value'},['a','b']) == 'present'


def test_conversion_errors_and_structural_validation():
    mapping={'name':'job_title','Min_YOE':'experience_years_min','crawled_at':'source_crawled_at'}
    raw={'name':'Developer','Min_YOE':'NA','crawled_at':'2025-10-22 16:42:25'}
    row,_,_=unified.adapt('example','x','a'*64,0,raw,mapping,['job_title','experience_years_min','source_crawled_at'])
    row.update(description='A'*120,requirements=None,raw_job_text=None,description_transformed=None)
    status,flags=quality.flag_record(row,mapping,raw,0,'a'*64)
    assert status=='usable'
    assert 'conversion_error:Min_YOE:sentinel' in flags and 'conversion_error:crawled_at:timezone_missing' in flags
    row['source_extra']=json.dumps({'Min_YOE':'different'})
    status,flags=quality.flag_record(row,mapping,raw,0,'a'*64)
    assert status=='needs_review' and 'conversion_original_not_preserved:Min_YOE' in flags
    row['experience_years_min']='invalid'
    assert not quality.check_type(row['experience_years_min'],'experience_years_min')


def test_bad_json_and_sentinel_title():
    assert not quality.check_type('{bad','requirements')
    status,flags=quality.judge(sample(job_title='null'))
    assert status=='needs_review' and 'sentinel:job_title' in flags
