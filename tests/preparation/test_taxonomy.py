import json
from src.preparation.taxonomy import enrich


def test_generic_title_uses_job_duties_for_role():
    result = enrich({'title':'Software Engineer', 'duties':'Build backend APIs and backend services.',
                     'requirements':'Python and SQL are required.'})
    assert (result['role_family'],result['primary_role']) == ('Software Engineering','Backend')
    assert any(e['field']=='duties' for e in json.loads(result['role_evidence']))


def test_skills_do_not_force_role():
    result = enrich({'title':'Technical Specialist', 'duties':'Support customers.',
                     'requirements':'Python, Docker and AWS.'})
    assert result['primary_role']=='unknown'
    assert result['skill_count']==3


def test_same_family_tie_retains_unknown_role():
    result = enrich({'title':'Backend Frontend Engineer', 'duties':'', 'requirements':''})
    assert result['role_family']=='Software Engineering'
    assert result['primary_role']=='unknown'


def test_incidental_testing_does_not_relabel_developer_as_qa():
    result = enrich({'title':'Software Engineer',
                     'duties':'Build web services and perform testing before release.',
                     'requirements':'Python, SQL and code review.'})
    assert result['role_family']=='Software Engineering'
    assert result['primary_role']=='unknown'


def test_specific_title_wins_over_other_role_in_body():
    result = enrich({'title':'Data Engineer',
                     'duties':'Collaborate with a QA engineer and security engineer.',
                     'requirements':'Python and Spark.'})
    assert (result['role_family'],result['primary_role']) == ('Data & AI','Data Engineer')


def test_observed_cloud_title_variants():
    for title in ('Cloud Operations Engineer', 'Cloud Solution Architect',
                  'IT - Cloud Platform Engineering Lead'):
        result = enrich({'title':title, 'duties':'Operate cloud systems.', 'requirements':'AWS.'})
        assert result['primary_role'] == 'Cloud'
