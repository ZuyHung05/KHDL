from src.preparation.role_report import role_for


def test_specific_role_wins_over_broad_software_title():
    assert role_for('Fullstack Software Developer') == ('Software Engineering', 'Fullstack')
    assert role_for('DevOps Engineer - Cloud Platform') == ('Infrastructure & Security', 'DevOps/SRE')
    assert role_for('Data Engineer (Python)') == ('Data & AI', 'Data Engineer')


def test_unspecified_title_is_not_forced_into_a_role():
    assert role_for('Technical Specialist') == ('Khác/chưa rõ nghề', 'Khác/chưa rõ')
