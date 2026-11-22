from src.preparation.eligibility import assess


def row(**kw):
    return {'job_title_clean':'Software Engineer', 'source_id':'careersgovsg', 'country_normalized':['Vietnam'], 'location_normalized':None, 'description_clean':'Duties: '+ 'Build software. '*15, 'requirements_clean':'Python and software development experience. '*3, **kw}


def test_independent_dimensions_and_source_not_geography():
    r = row(country_normalized=None, location_normalized=None)
    assert assess(r)[:4] == ('it','unknown','full_jd','needs_review')
    r['country_normalized'] = ['Vietnam']
    assert assess(r)[:4] == ('it','vietnam','full_jd','eligible')


def test_conflicting_geography():
    assert assess(row(country_normalized=['Singapore'],location_normalized=['Hà Nội']))[1] == 'unknown'
    assert assess(row(normalization_flags=['location_conflict']))[1] == 'unknown'


def test_ambiguous_title_and_non_it():
    assert assess(row(job_title_clean='Manager'))[0] == 'unknown'
    assert assess(row(job_title_clean='Accountant'))[0] == 'non_it'
    assert assess(row(job_title_clean='Software Engineer and Accountant'))[0] == 'unknown'


def test_special_sources_and_insufficient():
    assert assess(row(source_id='awesome_jobs_vietnam'))[2] == 'issue_unstructured'
    assert assess(row(description_clean=None, requirements_clean=None, description_transformed_clean='transformed'))[2] == 'transformed_text'
    assert assess(row(description_clean=None, requirements_clean=None, raw_job_text_clean=None))[2] == 'insufficient'
    assert assess(row(description_clean='Only a short description', requirements_clean=None))[2] == 'partial_jd'


def test_structured_in_one_field_and_deterministic():
    r = row(description_clean='Responsibilities: ' + 'Build software. '*20 + ' Requirements: Python', requirements_clean=None)
    assert assess(r)[2] == 'full_jd'
    assert assess(r) == assess(r)
