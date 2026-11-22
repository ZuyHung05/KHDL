from src.preparation.audit_reconciliation import classify_pair, inspect_cleaning
from src.preparation.deduplicate import exact_clusters


def row(rid,url,title='Cloud Engineer',company=None):
    return {'record_id':rid,'source_id':'topcv','source_job_id':None,'source_posting_id':None,'platform':None,'company_name':company,'source_url':url,'job_title_clean':title,'location_raw':None,'description_clean':'Cloud infrastructure '*20,'raw_job_text_clean':None,'description_transformed_clean':None}


def test_same_topcv_id_confirmed_different_ids_distinct():
    a=row('a','https://topcv.vn/viec-lam/cloud/100.html?u_sr_id=one')
    b=row('b','https://www.topcv.vn/viec-lam/cloud/100.html?u_sr_id=two')
    c=row('c','https://topcv.vn/viec-lam/cloud/101.html')
    assert classify_pair(a,b)[0]=='confirmed_duplicate'
    assert classify_pair(a,c)[0]=='distinct'
    clusters,_=exact_clusters([a,b,c])
    assert sorted(map(len,clusters))==[1,2]


def test_similar_text_does_not_confirm_other_sources():
    a=row('a','https://other.example/jobs/100');b=row('b','https://other.example/jobs/101')
    assert classify_pair(a,b)[0]=='uncertain'
    assert len(exact_clusters([a,b])[0])==2


def test_cleaning_audit_flags_removed_word():
    r={'record_id':'r','source_id':'x','job_title':'Cloud Engineer','job_title_clean':'Cloud Engineer','description':'<p>Python and SQL</p>','description_clean':'Python'}
    assert inspect_cleaning(r)['status']=='uncertain'
    r['description_clean']='Python and SQL'
    assert inspect_cleaning(r)['status']=='no_loss_detected_in_selected_characters'
