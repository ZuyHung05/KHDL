import random
from src.preparation.deduplicate import exact_clusters, select_rep, near_candidates, qa_review, multi_issue


def row(i,company='Acme',url=None,desc=None,title='Backend Engineer',location='Hanoi',**more):
    return {'record_id':str(i),'source_id':'source','source_job_id':None,'source_posting_id':None,'platform':None,'company_name':company,'source_url':url,'job_title_clean':title,'location_raw':location,'description_clean':desc or ('build systems safely and design reliable services '*12),'raw_job_text_clean':None,'description_transformed_clean':None,**more}


def groups(records):
    clusters,_=exact_clusters(records)
    return sorted(sorted(records[i]['record_id'] for i in c) for c in clusters)


def test_same_url_content_company_merges_but_different_company_does_not():
    records=[row('1',url='https://example.com/a?utm_source=x'),row('2',url='https://example.com/a'),row('3',company='Other',url='https://example.com/a')]
    assert groups(records)==[['1','2'],['3']]


def test_identical_template_different_url_or_missing_company_not_merged():
    assert groups([row('1',url='https://example.com/a'),row('2',url='https://example.com/b')])==[['1'],['2']]
    assert groups([row('1',company=None,url='https://example.com/a'),row('2',company=None,url='https://example.com/a')])==[['1'],['2']]


def test_topcv_identity_ignores_tracking_but_not_posting_or_employer():
    from src.preparation.deduplicate import topcv_posting_id
    a='https://www.topcv.vn/viec-lam/backend/123.html?ta_source=list&u_sr_id=abc'
    b='https://topcv.vn/viec-lam/backend/123.html?u_sr_id=other'
    assert topcv_posting_id(a)=='123' and topcv_posting_id('https://evil.test/viec-lam/backend/123.html') is None
    assert groups([row('1',company=None,url=a),row('2',company=None,url=b)])==[['1','2']]
    assert groups([row('1',company='A',url=a),row('2',company='B',url=b)])==[['1'],['2']]
    assert groups([row('1',url=a),row('2',url='https://topcv.vn/viec-lam/backend/124.html')])==[['1'],['2']]


def test_no_transitive_merge_of_conflicting_employers():
    records=[row('1',company='A',source_job_id='1'),row('2',company=None,source_job_id='1'),row('3',company='B',source_job_id='1')]
    assert groups(records)==[['1'],['2'],['3']]


def test_near_candidates_never_merge():
    a=' '.join('word'+str(i) for i in range(100))
    records=[row('a',url='https://example.com/a',desc=a),row('b',url='https://example.com/b',desc=a+' extra')]
    clusters,_=exact_clusters(records);near,stats=near_candidates(records,clusters)
    assert len(clusters)==2 and len(near)==1 and near[0]['status']=='needs_review'
    assert stats['oversized_blocks_skipped']==0


def test_representative_and_order_deterministic():
    a=row('a',url='https://example.com/a');b=row('b',url='https://example.com/a')
    assert select_rep([0,1],[a,b])==0
    arr=[a,b,row('c',company='Other')];expected=groups(arr);random.Random(42).shuffle(arr)
    assert groups(arr)==expected
    richer={**b,'requirements_clean':'["Detailed requirements"]'}
    assert select_rep([0,1],[a,richer])==1


def test_multiple_position_issue_and_qa():
    r=row('a');r.update(source_id='awesome_jobs_vietnam',job_title_clean='Hiring 7 roles',raw_job_text_clean='multiple positions')
    assert multi_issue(r)
    q={'job_title':'<h2>Developer</h2>','job_title_clean':'## Developer','description':'<p>C++ backend</p>','description_clean':'C++ backend'}
    assert all(x['finding']=='no_visible_token_loss_detected' for x in qa_review(q))
