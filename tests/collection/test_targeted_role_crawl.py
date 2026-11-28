from collections import Counter

from src.collection.targeted_role_crawl import (
    SEARCHES, canonical, choose_query, extract_itviec_detail, extract_itviec_rows, gaps, score_title, search_url,
)


def test_priority_uses_shortfall_not_family_size():
    counts = Counter({role: 80 for role in SEARCHES})
    counts['Cloud'], counts['UI/UX'], counts['DevOps/SRE'] = 6, 24, 58
    missing = gaps(counts, 80)
    assert [(r['role'], r['missing']) for r in missing[:2]] == [('Cloud', 74), ('UI/UX', 56)]
    assert [r['missing'] for r in missing if r['missing']] == [74, 56, 22]


def test_itviec_sections_and_location_are_specific_to_job_card():
    card = '''<div class="job-card"><h3><a href="https://itviec.com/it-jobs/cloud-engineer-acme-1234?lab_feature=x">Cloud Engineer</a></h3>
      <a href="/companies/acme"></a><a href="/companies/acme">Acme</a>
      <span>Hybrid</span><span>Ho Chi Minh</span></div>'''
    rows = extract_itviec_rows(card)
    assert rows == [{'job_url': 'https://itviec.com/it-jobs/cloud-engineer-acme-1234',
                     'site': 'itviec', 'title': 'Cloud Engineer', 'company': 'Acme',
                     'location': 'Ho Chi Minh'}]
    html = ('<div class="paragraph text-break"><h2>Job description</h2><p>'
            + 'Build and operate cloud systems. '*5 + '</p></div>'
            + '<div class="paragraph text-break"><h2>Your skills and experience</h2><p>'
            + 'Experience with Azure, AWS and Linux. '*3 + '</p></div>'
            + '<div class="paragraph text-break"><h2>Why you\'ll love working here</h2><p>Benefits</p></div>')
    detail = extract_itviec_detail(html)
    assert detail['parse_status'] == 'structured'
    assert 'Build and operate' in detail['duties']
    assert 'Experience with Azure' in detail['requirements']
    assert 'Benefits' not in detail['requirements']


def test_search_urls_and_canonical_url():
    assert search_url('topcv', 'cloud-engineer', 2).endswith('?page=2')
    assert search_url('itviec', 'cloud', 2).endswith('?page=2&source=search_job')
    assert canonical('https://itviec.com/it-jobs/foo?tracking=x') == 'https://itviec.com/it-jobs/foo'


def test_search_filters_unrelated_roles_and_sales():
    assert score_title({'title': 'Cloud Engineer'}, 'Cloud') == 0
    assert score_title({'title': 'Salesforce Cloud Developer'}, 'Cloud') == 2
    assert score_title({'title': 'Senior Sales Executive – Cybersecurity Solutions'}, 'Cybersecurity') == 2
    assert score_title({'title': 'Bridge System Engineer'}, 'System/Network/IT Support') == 2


def test_query_budget_advances_to_remaining_term():
    state = {'next_page': {'Cloud|itviec|cloud': 6}, 'exhausted': []}
    assert choose_query(state, 'Cloud', 'itviec', 5) == ('aws', 'Cloud|itviec|aws', 1)
    assert 'Cloud|itviec|cloud' in state['exhausted']
