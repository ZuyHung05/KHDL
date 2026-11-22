import json
from src.preparation.eligibility_v2 import assess

def base(**kw):
    r={'job_title_clean':'Manager','source_id':'other','country_normalized':None,'location_normalized':None,'description_clean':'','requirements_clean':'','responsibilities_clean':'','raw_job_text_clean':'','description_transformed_clean':''};r.update(kw);return r

def test_domain_requires_job_evidence():
    assert assess(base(description_clean='We use AWS and Python.'))[0]=='unknown'
    assert assess(base(description_clean='We develop software for customers.'))[0]=='unknown'
    assert assess(base(description_clean='You will develop software for customers.'))[0]=='it'
    assert assess(base(job_title_clean='Accountant',description_clean='You will develop software'))[0]=='unknown'
    assert assess(base(job_title_clean='Software Engineer and Accountant'))[0]=='unknown'
    assert assess(base(job_title_clean='Security Engineer'))[0]=='unknown'
    assert assess(base(job_title_clean='Security Engineer',description_clean='cyber security operations'))[0]=='it'
    assert assess(base(job_title_clean='QA Engineer'))[0]=='unknown'

def test_geography_evidence_and_conflict():
    assert assess(base(description_clean='Our company operates in Vietnam.'))[1]=='unknown'
    assert assess(base(description_clean='Location: Hanoi\nWork here.'))[1]=='vietnam'
    assert assess(base(country_normalized=['Singapore'],description_clean='Location: Hanoi'))[1]=='unknown'
    assert assess(base(country_normalized=['Singapore'],location_normalized=['Hà Nội'],description_clean='Location: Hanoi'))[1]=='unknown'
    assert assess(base(source_id='awesome_jobs_vietnam',description_clean='Location: Hanoi'))[1]=='unknown'

def test_skill_extractable_and_content_preservation():
    r=base(description_transformed_clean='Python, SQL, Docker')
    result=assess(r); assert result[2]=='transformed_text' and result[6]
    assert not assess(base(description_clean='Python SQL'))[6]
    assert assess(base(requirements_clean='Python and SQL'))[6]
    assert not assess(base(requirements_clean='Python Python'))[6]
    assert assess(base(source_id='awesome_jobs_vietnam',description_clean='Requirements: Python SQL'))[2]=='issue_unstructured'
    assert json.loads(result[5])['skill_extractability']

def test_deterministic():
    r=base(job_title_clean='Cloud Engineer',country_normalized=['Vietnam'],description_clean='Responsibilities: '+('software '*30)+' Requirements: '+('python '*20))
    assert assess(r)==assess(r)
