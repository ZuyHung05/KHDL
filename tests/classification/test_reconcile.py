from copy import deepcopy
from src.classification.dataset import content_hash,payload
from src.classification.reconcile import decide


def example():
    item={'jd_id':'legacy','title':'Software Engineer','description':'Build software.','requirements':'','preprocessing_version':'nfc_redact_v6'}
    suggestion={'jd_id':'legacy','primary_role':'unknown','role_family':None,'seniority':'unknown','evidence':[],'review_required':False,'review_reasons':[]}
    # Use a taxonomy role with exact title evidence instead of the unknown review sentinel.
    import yaml
    from src.classification.dataset import ROOT
    tax=yaml.safe_load((ROOT/'configs/role_taxonomy.yaml').read_text());family=next(iter(tax));role=next(iter(tax[family]))
    suggestion.update(primary_role=role,role_family=family,evidence=[{'target':'primary_role','field':'title','quote':'Software Engineer'}])
    versions={'model':'fixture','model_revision':'fixture-rev','corpus_manifest_sha256':'manifest','files_sha256':{'taxonomy':'hash'}}
    pred={'jd_id':'legacy','status':'PROPOSED','suggested':suggestion,'content_hash':content_hash(payload(item)),'versions':versions}
    target={**item,'jd_id':'m02'}
    return target,item,pred

def evaluate(target,item,pred):
    return decide(target,[item],{'legacy':pred},{'model':'fixture'},{'taxonomy':'hash'},'manifest')

def test_transfer_exact_input_and_remap_id():
    t,i,p=example();r=evaluate(t,i,p)
    assert r['status']=='transferred' and r['suggested']['jd_id']=='m02'
    assert p['suggested']['jd_id']=='legacy'

def test_input_hash_and_version_block():
    t,i,p=example();t['description']='Different input';assert not evaluate(t,i,p)['transferred']
    t,i,p=example();p['versions']['model']='other';assert 'version_mismatch' in evaluate(t,i,p)['reasons']

def test_pending_review_and_missing_do_not_transfer():
    t,i,p=example();p['status']='PENDING';assert evaluate(t,i,p)['status']=='pending'
    p['status']='REVIEW_REQUIRED';assert not evaluate(t,i,p)['transferred']
    assert decide(t,[i],{}, {},{},'manifest')['reasons']==['no_prediction']

def test_multi_legacy_conflict():
    t,i,p=example();i2={**i,'jd_id':'legacy2'};p2=deepcopy(p);p2['suggested'].update(jd_id='legacy2',primary_role='other_it_role',role_family=None)
    result=decide(t,[i,i2],{'legacy':p,'legacy2':p2},{'model':'fixture'},{'taxonomy':'hash'},'manifest')
    assert result['status']=='conflict' and not result['transferred']

def test_invalid_evidence_blocks():
    t,i,p=example();p['suggested']['evidence'][0]['quote']='not in title'
    assert 'invalid_schema_or_evidence' in evaluate(t,i,p)['reasons']
