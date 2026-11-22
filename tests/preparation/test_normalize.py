import json
from datetime import datetime,timezone
import yaml
from src.preparation.normalize import ROOT,normalize_record,value

RULES=yaml.safe_load((ROOT/'configs/field_normalization.yaml').read_text(encoding='utf-8'))


def test_explicit_location_and_multi():
    r=normalize_record({'source_id':'x','location_raw':'Hà Nội, Hồ Chí Minh','country':'Việt Nam'},RULES)
    assert r['location_normalized']==['Hà Nội','Hồ Chí Minh'] and r['country_normalized']==['Vietnam']
    assert normalize_record({'source_id':'x','location_raw':'Hà Nội','city':'Hồ Chí Minh'},RULES)['location_normalized'] is None
    assert 'location_conflict' in normalize_record({'source_id':'x','location_raw':'Hà Nội','city':'Hồ Chí Minh'},RULES)['normalization_flags']


def test_missing_ambiguous_and_unknown():
    assert value(' NA ') is None
    r=normalize_record({'source_id':'x','city':'N/A','location_raw':None,'source_level_fields':'{"L1":"2"}'},RULES)
    assert r['seniority_normalized'] is None and 'seniority_source_codes_unmapped' in r['normalization_flags']
    r=normalize_record({'source_id':'x','seniority_source':'Fresher, Junior'},RULES)
    assert r['seniority_normalized'] is None and 'seniority_multiple' in r['normalization_flags']


def test_experience_and_timezone_are_not_inferred():
    r=normalize_record({'source_id':'careersgovsg','experience_years_min':0.0,'experience_years_max':0.0,'experience_raw':'"Entry level"'},RULES)
    assert r['experience_years_min_normalized'] is None and 'experience_zero_range_ambiguous' in r['normalization_flags']
    r=normalize_record({'source_id':'x','experience_years_min':5.0,'experience_years_max':2.0,'posted_at':datetime(2024,1,1)},RULES)
    assert r['experience_years_min_normalized'] is None and 'experience_range_conflict' in r['normalization_flags'] and 'posted_at_timezone_missing' in r['normalization_flags']
    now=datetime(2024,1,1,tzinfo=timezone.utc)
    assert normalize_record({'source_id':'x','posted_at':now},RULES)['posted_at_normalized']==now


def test_multiple_terms_and_arrangement_conflict():
    row={'source_id':'data_job_analysis','employment_type':'Fulltime','source_extra':json.dumps({'W_Term_2':'Contract','W_Term_3':'Hybrid'}),'source_remote_flag':'"1"'}
    r=normalize_record(row,RULES)
    assert r['employment_type_normalized']==['contract','full_time'] and 'employment_multiple' in r['normalization_flags']
    assert r['work_arrangement_normalized'] is None and 'work_arrangement_conflict' in r['normalization_flags']
    assert normalize_record({'source_id':'careersgovsg','work_arrangement':'Full-time'},RULES)['work_arrangement_normalized'] is None


def test_deterministic():
    row={'source_id':'x','location_raw':'Hà Nội','employment_type':'Full-time','work_arrangement':'Remote'}
    assert normalize_record(row,RULES)==normalize_record(row,RULES)
