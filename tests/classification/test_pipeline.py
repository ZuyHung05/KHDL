import json
import pytest
from pydantic import ValidationError
from src.classification.dataset import payload, content_hash, sample_candidates, api_description
from src.classification.state import State, cache_key, project_lock
from src.classification.validation import validate, evidence_offsets


def make_proposal():
    return {'jd_id': '1', 'primary_role': 'Backend', 'role_family': 'Software Engineering',
            'seniority': 'unknown', 'evidence': [{'target': 'primary_role', 'field': 'description', 'quote': 'Build APIs'}],
            'review_required': False, 'review_reasons': []}


def test_payload_mapping_and_hash():
    record = {'jd_id': 'one', 'title': 'C++', 'description': 'build', 'api_description': '<p>Build APIs</p>',
              'requirements': 'Email a@example.com or 0912345678'}
    job = payload(record)
    assert 'C++' == job['title'] and 'Build APIs' in job['description']
    assert 'a@example.com' not in job['requirements'] and '0912345678' not in job['requirements']
    assert content_hash(job) == content_hash({**job, 'jd_id': 'another'})
    assert api_description('careersgovsg', {'jobResponsibilities': 'Develop systems'}, 'Summary') == 'Summary\n\nDevelop systems'


def test_schema_validation_and_offsets():
    item = {'jd_id': '1', 'title': 'Developer', 'description': 'Build APIs with AWS', 'requirements': ''}
    response = make_proposal()
    assert evidence_offsets(validate(response, item), item)[0]['start'] == 0
    for field, value in [('jd_id', 'wrong'), ('primary_role', 'Cloud'), ('role_family', 'Data & AI')]:
        with pytest.raises(ValueError): validate({**response, field: value}, item)
    with pytest.raises((ValidationError, ValueError)): validate({**response, 'extra': True}, item)
    with pytest.raises(ValueError): validate({**response, 'evidence': [{**response['evidence'][0], 'quote': 'invented'}]}, item)
    with pytest.raises(ValueError): validate({**response, 'primary_role': 'unknown', 'role_family': None}, item)


def test_samples_are_deterministic_and_disjoint():
    from src.classification.dataset import audit_samples
    records = [{'jd_id': str(i), 'content_hash': str(i // 2), 'rule_status': 'unknown' if i % 4 else 'needs_review',
                'source_members': [{'source_id': 'a' if i % 3 else 'b'}]} for i in range(600)]
    samples = sample_candidates(records)
    assert samples == sample_candidates(records)
    a, b = samples['stages']['smoke50'], samples['stages']['pilot200']
    assert len(a) == 50 and len(b) == 200
    assert {x['content_hash'] for x in a}.isdisjoint(x['content_hash'] for x in b)
    assert all(0 < x['group_inclusion_probability'] <= 1 for x in a + b)
    audit = audit_samples(records, samples)
    assert audit['candidate_input_groups'] == 300
    assert audit['eligible_groups_after_smoke'] == 250
    assert sum(row['pilot_groups'] for row in audit['strata']) == 200
    assert audit['probability_scope'] == 'conditional on smoke sample removed'
    samples['stages']['pilot200'][0]['group_inclusion_probability'] = 0.123456
    with pytest.raises(ValueError, match='probability'):
        audit_samples(records, samples)


def test_state_cache_atomicity_recovery_and_lock(tmp_path):
    state = State(tmp_path / 'state.sqlite')
    key = cache_key({'content_hash': 'x', 'model_version': 'v1'})
    assert key != cache_key({'content_hash': 'x', 'model_version': 'v2'})
    state.create_run('r', {'model': 'm'}, [('1', key)])
    assert state.claim('r', '1') and not state.claim('r', '1')
    state.recover('r')
    assert state.claim('r', '1')
    state.finish('r', '1', key, make_proposal(), 'v1')
    assert state.cached(key)[0]['jd_id'] == ''
    state.close()
    with project_lock(tmp_path / 'lock'):
        with pytest.raises(RuntimeError):
            with project_lock(tmp_path / 'lock'): pass


def test_quota_rate_daily_run_budget_and_pacific_reset(tmp_path):
    from datetime import datetime, timedelta, timezone
    from src.classification.quota import reserve, RateWait, QuotaPaused
    state = State(tmp_path / 'quota.sqlite')
    cfg = {'rpm': 3, 'input_tpm': 1000, 'rpd': 3, 'max_requests_per_run': 10,
           'max_input_tokens_per_run': 10000, 'project_id': 'project'}
    # 23:59 Pacific Standard Time; midnight occurs at 08:00 UTC.
    now = datetime(2026, 1, 1, 7, 59, tzinfo=timezone.utc)
    reserve(state, 'run', cfg, 100, now)
    reserve(state, 'run', cfg, 100, now + timedelta(seconds=1))
    with pytest.raises(QuotaPaused, match='Daily'):
        reserve(state, 'run', cfg, 100, now + timedelta(seconds=2))
    reserve(state, 'run', cfg, 100, now + timedelta(seconds=62))
    state.close()
    other = State(tmp_path / 'other.sqlite')
    cfg['rpd'] = 100
    reserve(other, 'run', cfg, 100, now)
    reserve(other, 'run', cfg, 100, now + timedelta(seconds=1))
    with pytest.raises(RateWait):
        reserve(other, 'run', cfg, 100, now + timedelta(seconds=2))
    other.close()


def test_engine_cache_evidence_correction_and_429(tmp_path):
    from types import SimpleNamespace
    from src.classification.engine import classify_one
    from src.classification.quota import QuotaPaused
    cfg = {'rpm': 100, 'input_tpm': 200000, 'rpd': 100, 'max_requests_per_run': 20,
           'max_input_tokens_per_run': 1000000, 'project_id': 'test'}
    job = {'jd_id': '1', 'title': 'Developer', 'description': 'Build APIs with AWS', 'requirements': ''}
    state = State(tmp_path / 'run.sqlite')
    state.create_run('r', {'actual_model_version': None}, [('1', 'k'), ('2', 'k'), ('3', 'other')])
    class Client:
        calls = 0
        def generate(self, item, correction=False):
            self.calls += 1
            result = {**make_proposal(), 'jd_id': item['jd_id']}
            if self.calls == 1:
                result['evidence'] = [{**result['evidence'][0], 'quote': 'not in text'}]
            return SimpleNamespace(parsed=result, model_version='revision', usage_metadata=None)
    client = Client()
    actual = classify_one(state, 'r', job, 'k', client, cfg, None, sleep=lambda _: None)
    assert actual == 'revision' and client.calls == 1
    assert state.db.execute("SELECT status FROM tasks WHERE jd_id='1'").fetchone()[0] == 'REVIEW_REQUIRED'
    classify_one(state, 'r', {**job, 'jd_id': '2'}, 'k', client, cfg, actual, sleep=lambda _: None)
    assert client.calls == 2
    assert state.db.execute("SELECT status,cache_hit FROM tasks WHERE jd_id='2'").fetchone() == ('PROPOSED', 0)
    class RateError(Exception): code = 429
    class Limited:
        def generate(self, *args, **kwargs): raise RateError('secret prompt')
    with pytest.raises(QuotaPaused):
        classify_one(state, 'r', {**job, 'jd_id': '3'}, 'other', Limited(), cfg, actual, sleep=lambda _: None)
    assert state.db.execute("SELECT status FROM tasks WHERE jd_id='3'").fetchone()[0] == 'PENDING'
    errors = state.db.execute('SELECT error_code FROM attempts WHERE error_code IS NOT NULL').fetchall()
    assert errors == [('SCHEMA_OR_EVIDENCE',), ('429',)]
    state.close()


def test_engine_empty_does_not_use_api(tmp_path):
    from src.classification.engine import classify_one
    state = State(tmp_path / 'empty.sqlite')
    state.create_run('r', {}, [('x', 'k')])
    assert classify_one(state, 'r', {'jd_id': 'x', 'title': 'x', 'description': '[contact removed]', 'requirements': ''}, 'k', None, {}, None) is None
    assert state.db.execute("SELECT status FROM tasks").fetchone()[0] == 'REVIEW_REQUIRED'
    assert state.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 0
    state.close()


def test_provider_schema_is_compatible_subset():
    from google.genai import _transformers
    from src.classification.gemini_client import provider_schema
    schema = provider_schema()
    encoded = json.dumps(schema)
    assert 'additionalProperties' not in encoded and 'maxLength' not in encoded
    assert _transformers.t_schema(None, schema) is not None


def test_evaluation_refuses_incomplete_pilot_and_unblind_gold():
    from src.classification.evaluation import evaluate
    annotations = [{'annotator': 'a', 'blind': True, 'guideline_version': 'v1', 'role': 'Backend'},
                   {'annotator': 'b', 'blind': True, 'guideline_version': 'v1', 'role': 'Backend'}]
    gold = [{'jd_id': '1', 'role': 'Backend', 'seniority': 'unknown', 'multiple_roles': False, 'ambiguous': False,
             'annotations': annotations, 'adjudicated': True, 'adjudicator': 'a',
             'evidence': [{'target': 'primary_role', 'field': 'description', 'quote': 'Build APIs'}]}]
    inputs = {'1': {'jd_id': '1', 'title': 'Developer', 'description': 'Build APIs', 'requirements': ''}}
    predictions = [{'jd_id': '1', 'status': 'PROPOSED', 'suggested': make_proposal(), 'validation_status': 'VALID'}]
    result = evaluate(predictions, gold, ['1'], 1, 1, inputs=inputs)
    assert result['metrics']['Backend']['f1'] == 1
    assert result['cloud_requires_review'] and not result['full_gate']
    gold[0]['annotations'][0]['blind'] = False
    with pytest.raises(ValueError, match='independent blind'):
        evaluate(predictions, gold, ['1'], 1, 1, inputs=inputs)


def test_coverage_counts_exclude_invalid_and_unverified_cloud():
    from src.classification.reporting import coverage
    base = {'jd_id': '1', 'title': 'Engineer', 'description': 'Build APIs with AWS', 'requirements': '',
            'rule_status': 'unknown', 'rule_primary_role': None}
    task = {'1': {'status': 'PROPOSED', 'suggested': make_proposal()}}
    _, before, after, _ = coverage([base], task)
    assert sum(x['count'] for x in after) == 1
    assert next(x['count'] for x in before if x['label'] == 'unknown') == 1
    assert next(x['count'] for x in after if x['label'] == 'Backend') == 1
    task['1']['suggested']['evidence'][0]['quote'] = 'invented'
    _, _, after, _ = coverage([base], task)
    assert next(x['count'] for x in after if x['label'] == 'unknown') == 1


def test_cloud_is_forced_to_review_without_gold(tmp_path):
    from types import SimpleNamespace
    from src.classification.engine import classify_one
    job = {'jd_id': '1', 'title': 'Cloud architect', 'description': 'Design cloud platforms', 'requirements': ''}
    answer = {'jd_id': '1', 'primary_role': 'Cloud', 'role_family': 'Infrastructure & Security',
              'seniority': 'unknown', 'evidence': [{'target': 'primary_role', 'field': 'description', 'quote': 'Design cloud platforms'}],
              'review_required': False, 'review_reasons': []}
    class Client:
        def generate(self, *args, **kwargs):
            return SimpleNamespace(parsed=answer, model_version='v', usage_metadata=None)
    cfg = {'rpm': 100, 'input_tpm': 200000, 'rpd': 100, 'max_requests_per_run': 20,
           'max_input_tokens_per_run': 1000000, 'project_id': 'test'}
    state = State(tmp_path / 'cloud.sqlite'); state.create_run('r', {}, [('1', 'key')])
    classify_one(state, 'r', job, 'key', Client(), cfg, None)
    status, value = state.db.execute('SELECT status,result FROM tasks').fetchone()
    assert status == 'REVIEW_REQUIRED' and 'cloud_insufficient_gold' in json.loads(value)['review_reasons']
    cached, _ = state.cached('key')
    assert cached['review_required'] is False
    state.create_run('later', {}, [('1', 'key')])
    classify_one(state, 'later', job, 'key', None, cfg, 'v', cloud_requires_review=False)
    assert state.db.execute("SELECT status,cache_hit FROM tasks WHERE run_id='later'").fetchone() == ('PROPOSED', 1)
    state.close()


def test_smoke_gate_requires_all_reviewed(tmp_path):
    from src.classification.workflow import verify_smoke_review
    state = State(tmp_path / 'state.sqlite')
    manifest = {'corpus_id': 'c', 'stage': 'smoke50', 'actual_model_version': 'v'}
    state.create_run('smoke', manifest, [(str(i), str(i)) for i in range(50)])
    with state.db:
        state.db.execute("UPDATE runs SET status='COMPLETED'")
        state.db.execute("UPDATE tasks SET status='REVIEW_REQUIRED'")
    review = {'run_id': 'smoke', 'reviewer': 'human', 'all_reviewed': True, 'prompt_frozen': True,
              'reviewed_jd_ids': [str(i) for i in range(50)]}
    path = tmp_path / 'review.json'; path.write_text(json.dumps(review))
    assert verify_smoke_review(state, 'c', path)['stage'] == 'smoke50'
    review['reviewed_jd_ids'].pop(); path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match='each sample'): verify_smoke_review(state, 'c', path)
    state.close()


def test_unknown_usage_is_not_reported_as_zero(tmp_path):
    from src.classification.workflow import summarize
    state = State(tmp_path / 'usage.sqlite')
    state.create_run('r', {}, [('1', 'k')])
    attempt = state.begin_attempt('r', '1', '2026-01-01T00:00:00+00:00')
    state.end_attempt(attempt, 'ERROR', '504', 100, {'unknown_usage': True})
    report = summarize(state, 'r')
    assert report['unknown_usage'] == 1
    assert all(value is None for value in report['usage_observed'].values())
    assert report['estimated_cost'] is None
    state.close()


def test_provider_504_retries_are_bounded(tmp_path):
    from src.classification.engine import classify_one
    class Timeout(Exception): code = 504
    class Client:
        calls = 0
        def generate(self, *args, **kwargs):
            self.calls += 1
            raise Timeout('must not be logged')
    cfg = {'rpm': 100, 'input_tpm': 200000, 'rpd': 100, 'max_requests_per_run': 20,
           'max_input_tokens_per_run': 1000000, 'project_id': 'test'}
    state = State(tmp_path / 'timeout.sqlite'); state.create_run('r', {}, [('1', 'k')]); client = Client()
    classify_one(state, 'r', {'jd_id': '1', 'title': 'x', 'description': 'Build APIs', 'requirements': ''},
                 'k', client, cfg, None, sleep=lambda _: None)
    assert client.calls == 3
    assert state.db.execute('SELECT status FROM tasks').fetchone()[0] == 'FAILED'
    assert state.db.execute('SELECT COUNT(*) FROM quota_requests').fetchone()[0] == 3
    assert all(x[0] == '504' for x in state.db.execute('SELECT error_code FROM attempts'))
    state.close()


def test_model_metadata_counts_toward_run_request_cap(tmp_path):
    from datetime import datetime, timezone, timedelta
    from src.classification.quota import reserve, QuotaPaused
    state = State(tmp_path / 'quota.sqlite')
    cfg = {'rpm': 5, 'input_tpm': 1000, 'rpd': 20, 'max_requests_per_run': 2,
           'max_input_tokens_per_run': 1000, 'project_id': 'p'}
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    reserve(state, 'r', cfg, 0, now, kind='model_metadata')
    reserve(state, 'r', cfg, 10, now + timedelta(seconds=1))
    with pytest.raises(QuotaPaused, match='run budget'):
        reserve(state, 'r', cfg, 10, now + timedelta(seconds=2))
    state.close()


def test_safety_refusal_is_review_without_schema_retry(tmp_path):
    from types import SimpleNamespace
    from src.classification.engine import classify_one
    class Client:
        calls = 0
        def generate(self, *args, **kwargs):
            self.calls += 1
            return SimpleNamespace(model_version='v', usage_metadata=None, prompt_feedback=SimpleNamespace(block_reason='SAFETY'))
    cfg = {'rpm': 100, 'input_tpm': 200000, 'rpd': 100, 'max_requests_per_run': 20,
           'max_input_tokens_per_run': 1000000, 'project_id': 'p'}
    state = State(tmp_path / 'state.sqlite'); state.create_run('r', {}, [('1','k')]); client = Client()
    classify_one(state, 'r', {'jd_id':'1', 'title':'x', 'description':'abc', 'requirements':''}, 'k', client, cfg, None)
    status, value = state.db.execute('SELECT status,result FROM tasks').fetchone()
    assert client.calls == 1 and status == 'REVIEW_REQUIRED'
    assert json.loads(value)['reason'] == 'safety_or_refusal'
    state.close()


def test_full_gate_refuses_missing_or_non_pilot(tmp_path, monkeypatch):
    from src.classification import workflow
    state = State(tmp_path / 'state.sqlite')
    state.create_run('r', {'stage': 'pilot5', 'corpus_id': 'c'}, [])
    with state.db: state.db.execute("UPDATE runs SET status='COMPLETED'")
    monkeypatch.setattr(workflow, 'BASE', tmp_path)
    with pytest.raises(ValueError, match='independent pilot200'):
        workflow.verify_pilot_gate(state, 'c', 'r')
    with pytest.raises(ValueError, match='not found'):
        workflow.verify_pilot_gate(state, 'c', 'missing')
    state.close()


def test_explicit_multiple_positions_never_calls_api(tmp_path):
    from src.classification.engine import classify_one
    state = State(tmp_path / 'state.sqlite'); state.create_run('r', {}, [('1','k')])
    job = {'jd_id':'1', 'title':'Hiring', 'description':'Hiring multiple positions for the team', 'requirements':''}
    classify_one(state, 'r', job, 'k', None, {}, None)
    status, result = state.db.execute('SELECT status,result FROM tasks').fetchone()
    assert status == 'REVIEW_REQUIRED' and json.loads(result)['reason'] == 'multiple_positions'
    assert state.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 0
    state.close()


def test_pilot_gate_rejects_pending_even_with_200_predictions():
    from src.classification.evaluation import evaluate
    gold, predictions, inputs, ids = [], [], {}, []
    for i in range(200):
        jd = str(i); ids.append(jd)
        inputs[jd] = {'jd_id': jd, 'title': 'Backend developer', 'description': 'Build APIs', 'requirements': ''}
        gold.append({'jd_id': jd, 'role': 'Backend', 'seniority': 'unknown', 'multiple_roles': False, 'ambiguous': False,
                     'adjudicated': True, 'adjudicator': 'a',
                     'annotations': [{'annotator': x, 'blind': True, 'guideline_version': 'v1', 'role': 'Backend'} for x in ('a','b')],
                     'evidence': [{'target':'primary_role','field':'description','quote':'Build APIs'}]})
        result = {**make_proposal(), 'jd_id': jd}
        predictions.append({'jd_id': jd, 'status': 'PROPOSED', 'suggested': result, 'validation_status': 'VALID'})
    predictions[0] = {'jd_id': '0', 'status': 'PENDING', 'suggested': None}
    result = evaluate(predictions, gold, ids, 199, 199, inputs=inputs)
    assert not result['gate_checks']['complete_independent_pilot']
    assert not result['full_gate']


def test_offline_workflow_counts_model_check_and_checkpoints(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.classification import workflow
    corpora = tmp_path / 'corpora'; base = corpora / 'fixture'; base.mkdir(parents=True)
    records = []
    for i in range(5):
        records.append({'jd_id': str(i), 'title': 'Developer', 'description': f'Build APIs {i}', 'requirements': '',
                        'source_members': [{'source_id': f'source{i}'}], 'rule_status': 'unknown', 'rule_primary_role': None})
    def lines(path, objects):
        path.write_text(''.join(json.dumps(o) + '\n' for o in objects))
    lines(base / 'candidates.jsonl', records)
    lines(base / 'smoke50_payload_review.jsonl', [payload(r) for r in records])
    (base / 'samples.json').write_text(json.dumps({'stages': {'smoke50': [{'jd_id': r['jd_id'], 'source_id': r['source_members'][0]['source_id']} for r in records]}}))
    (base / 'corpus_manifest.json').write_text(json.dumps({'preprocessing_version': 'nfc_redact_v6'}))
    class Client:
        def model_revision(self): return 'v1'
        def generate(self, item, correction=False):
            return SimpleNamespace(parsed={**make_proposal(), 'jd_id': item['jd_id']}, model_version='v1', usage_metadata=None)
    monkeypatch.setattr(workflow, 'OUT', corpora)
    monkeypatch.setattr(workflow, 'BASE', tmp_path / 'output')
    monkeypatch.setattr(workflow, 'load_client', lambda *a, **k: Client())
    monkeypatch.setattr('src.classification.engine.estimate_tokens', lambda item: 100)
    monkeypatch.setenv('GEMINI_MODEL', 'gemini-3.5-flash-lite')
    result = workflow.start_run('fixture', 'pilot5', 'mock_run', True, lambda _: {'artifact_hashes_verified': True})
    assert result['status'] == 'COMPLETED'
    assert result['quota_requests_by_kind'] == {'generate': 5, 'model_metadata': 1}
    assert result['tasks'] == {'PROPOSED': 5}
    stored = [json.loads(x) for x in (tmp_path / 'output/runs/mock_run/predictions.jsonl').read_text().splitlines()]
    assert len(stored) == 5 and sum(r['status'] == 'PROPOSED' for r in stored) == 5


def test_preprocessing_versions_preserve_frozen_input_and_symbols():
    from src.classification.dataset import sanitize
    text = '## Heading\n**C++**, C#, .NET [apply](https://example.com)'
    assert '**C++**' in sanitize(text, 'nfc_redact_v2')
    newer = sanitize(text, 'nfc_redact_v4')
    assert '##' not in newer and '**' not in newer and 'example.com' not in newer
    assert all(symbol in newer for symbol in ('C++', 'C#', '.NET'))
    assert sanitize('Application Support Engineer', 'nfc_redact_v5') == 'Application Support Engineer'
    assert 'Application development' in sanitize('Application development in C++', 'nfc_redact_v5')
    assert '<T>' in sanitize('Use generics <T> and C++', 'nfc_redact_v5')
    assert 'someone@example.com' not in sanitize('## Contact\nsomeone@example.com\n## Responsibilities\nBuild APIs', 'nfc_redact_v5')
    assert 'Build APIs' in sanitize('## Contact\nsomeone@example.com\n## Responsibilities\nBuild APIs', 'nfc_redact_v5')
    assert '@example_handle' not in sanitize('• Telegram ID: @example_handle', 'nfc_redact_v6')
    assert 'Telegram bot development' in sanitize('Telegram bot development', 'nfc_redact_v6')


def test_invalid_response_retry_budget_survives_restart(tmp_path):
    from types import SimpleNamespace
    from src.classification.engine import classify_one
    state = State(tmp_path / 'state.sqlite')
    state.create_run('r', {'actual_model_version': 'v'}, [('1', 'k')])
    prior = state.begin_attempt('r', '1', '2026-01-01T00:00:00+00:00')
    state.end_attempt(prior, 'INVALID_RESPONSE', 'SCHEMA_OR_EVIDENCE')
    class Client:
        corrections = []
        def generate(self, item, correction=False):
            self.corrections.append(correction)
            return SimpleNamespace(parsed={**make_proposal(), 'jd_id': item['jd_id']}, model_version='v', usage_metadata=None)
    cfg = {'rpm': 100, 'input_tpm': 200000, 'rpd': 100, 'max_requests_per_run': 20,
           'max_input_tokens_per_run': 1000000, 'project_id': 'test'}
    job = {'jd_id': '1', 'title': 'Developer', 'description': 'Build APIs', 'requirements': ''}
    client = Client()
    classify_one(state, 'r', job, 'k', client, cfg, 'v')
    assert client.corrections == []
    assert state.db.execute('SELECT status FROM tasks').fetchone()[0] == 'REVIEW_REQUIRED'
    state.close()


def test_interrupted_after_two_invalid_responses_does_not_call_api(tmp_path):
    from src.classification.engine import classify_one
    state = State(tmp_path / 'state.sqlite'); state.create_run('r', {}, [('1', 'k')])
    for _ in range(2):
        attempt = state.begin_attempt('r', '1', '2026-01-01T00:00:00+00:00')
        state.end_attempt(attempt, 'INVALID_RESPONSE', 'SCHEMA_OR_EVIDENCE')
    job = {'jd_id': '1', 'title': 'Developer', 'description': 'Build APIs', 'requirements': ''}
    classify_one(state, 'r', job, 'k', None, {}, None)
    assert state.db.execute('SELECT status FROM tasks').fetchone()[0] == 'REVIEW_REQUIRED'
    assert state.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 2
    state.close()


def test_unexpected_run_error_is_not_marked_completed(tmp_path, monkeypatch):
    from src.classification import workflow
    state = State(tmp_path / 'state.sqlite')
    state.create_run('r', {}, [('1', 'k')])
    def fail(*args, **kwargs):
        raise RuntimeError('unexpected internal error')
    monkeypatch.setattr(workflow, 'classify_one', fail)
    monkeypatch.setattr(workflow, 'export_run', lambda *args: None)
    manifest = {'run_id': 'r', 'config': {'quota': {}, 'max_input_characters': 1000}}
    records = [{'jd_id': '1', 'title': 'x', 'description': 'work', 'requirements': ''}]
    with pytest.raises(RuntimeError, match='unexpected'):
        workflow.execute(state, None, manifest, records)
    assert state.db.execute('SELECT status FROM runs').fetchone()[0] == 'INTERRUPTED'
    state.close()


def test_evaluation_separates_missing_results_and_unexercised_cloud_case(tmp_path):
    from src.classification.evaluation import evaluate, plot_confusion
    ids = ['uncertain', 'cloud_case']
    inputs = {
        'uncertain': {'jd_id': 'uncertain', 'title': 'Vacancy', 'description': 'No details', 'requirements': ''},
        'cloud_case': {'jd_id': 'cloud_case', 'title': 'Accountant', 'description': 'Use AWS billing software', 'requirements': ''},
    }
    def gold_row(jd, role):
        return {'jd_id': jd, 'role': role, 'seniority': 'unknown', 'ambiguous': False, 'multiple_roles': False,
                'adjudicated': True, 'adjudicator': 'a',
                'annotations': [{'annotator': x, 'blind': True, 'guideline_version': 'v1', 'role': role} for x in ('a', 'b')],
                'evidence': [] if role == 'unknown' else [{'target': 'primary_role', 'field': 'title', 'quote': 'Accountant'}]}
    gold = [gold_row('uncertain', 'unknown'), {**gold_row('cloud_case', 'non_it'), 'cloud_counterexample': True}]
    predictions = [{'jd_id': jd, 'status': 'REVIEW_REQUIRED', 'suggested': None} for jd in ids]
    result = evaluate(predictions, gold, ids, 0, 0, inputs=inputs)
    assert result['confusion_matrix']['unknown']['unresolved'] == 1
    assert result['confusion_matrix']['unknown']['unknown'] == 0
    assert result['metrics']['unknown']['recall'] == 0
    assert result['cloud_counterexamples_untested'] == 1
    assert not result['gate_checks']['cloud_counterexample_tested_and_passed']
    path = tmp_path / 'confusion.png'
    plot_confusion(result, path)
    assert path.stat().st_size > 0


def test_independent_cloud_suite_uses_validated_existing_outputs(tmp_path, monkeypatch):
    from src.classification import workflow
    state = State(tmp_path / 'state.sqlite')
    versions = {'model': 'mock', 'model_revision': 'v1'}
    pilot = {'run_id': 'pilot', 'corpus_id': 'c', 'versions': versions,
             'actual_model_version': 'v1', 'selected_jd_ids': ['pilot_jd']}
    case_manifest = {'run_id': 'cases', 'corpus_id': 'c', 'versions': versions,
                     'actual_model_version': 'v1', 'selected_jd_ids': ['case_jd']}
    state.create_run('cases', case_manifest, [('case_jd', 'key')])
    with state.db: state.db.execute("UPDATE runs SET status='COMPLETED' WHERE run_id='cases'")
    corpus = tmp_path / 'corpora/c'; corpus.mkdir(parents=True)
    records = [{'jd_id': 'pilot_jd', 'title': 'Developer', 'description': 'Build APIs', 'requirements': '', 'content_hash': 'a'},
               {'jd_id': 'case_jd', 'title': 'Accountant', 'description': 'Use AWS billing software', 'requirements': '', 'content_hash': 'b'}]
    (corpus / 'candidates.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in records))
    run_dir = tmp_path / 'out/runs/cases'; run_dir.mkdir(parents=True)
    (run_dir / 'run_manifest.json').write_text(json.dumps(case_manifest))
    proposal = {'jd_id': 'case_jd', 'primary_role': 'non_it', 'role_family': None, 'seniority': 'unknown',
                'review_required': False, 'review_reasons': [],
                'evidence': [{'target': 'primary_role', 'field': 'title', 'quote': 'Accountant'}]}
    state.claim('cases', 'case_jd')
    state.finish('cases', 'case_jd', 'key', proposal, 'v1')
    (run_dir / 'predictions.jsonl').write_text(json.dumps({'jd_id': 'case_jd', 'status': 'PROPOSED', 'suggested': proposal, 'validation_status': 'VALID', 'cache_hit': False}) + '\n')
    gold = {'jd_id': 'case_jd', 'role': 'non_it', 'seniority': 'unknown', 'ambiguous': False,
            'multiple_roles': False, 'cloud_counterexample': True, 'adjudicated': True, 'adjudicator': 'a',
            'annotations': [{'annotator': x, 'blind': True, 'guideline_version': 'v1', 'role': 'non_it'} for x in ('a', 'b')],
            'evidence': [{'target': 'primary_role', 'field': 'title', 'quote': 'Accountant'}]}
    gold_path = tmp_path / 'gold.jsonl'; gold_path.write_text(json.dumps(gold) + '\n')
    monkeypatch.setattr(workflow, 'OUT', tmp_path / 'corpora')
    monkeypatch.setattr(workflow, 'BASE', tmp_path / 'out')
    result, evidence = workflow.read_cloud_suite(state, pilot, 'cases', gold_path)
    assert result == {'count': 1, 'errors': 0, 'untested': 0}
    assert len(evidence['gold_sha256']) == 64
    modified = {**proposal, 'primary_role': 'unknown', 'role_family': None, 'review_required': True}
    (run_dir / 'predictions.jsonl').write_text(json.dumps({'jd_id': 'case_jd', 'status': 'PROPOSED', 'suggested': modified, 'validation_status': 'VALID', 'cache_hit': False}) + '\n')
    with pytest.raises(ValueError, match='checkpoint'):
        workflow.read_cloud_suite(state, pilot, 'cases', gold_path)
    pilot['selected_jd_ids'] = ['case_jd']
    with pytest.raises(ValueError, match='independent'):
        workflow.read_cloud_suite(state, pilot, 'cases', gold_path)
    state.close()


def test_sampling_represents_small_strata_when_feasible():
    from src.classification.dataset import audit_samples
    records = []
    for source, count in [('large', 300), ('small_a', 3), ('small_b', 4)]:
        for index in range(count):
            ident = f'{source}-{index}'
            records.append({'jd_id': ident, 'content_hash': ident, 'rule_status': 'unknown',
                            'source_members': [{'source_id': source}]})
    samples = sample_candidates(records)
    audit = audit_samples(records, samples)
    assert audit['unrepresented_strata'] == []
    assert {x['source_id'] for x in samples['stages']['pilot200']} == {'large', 'small_a', 'small_b'}


def test_weighted_group_estimates_use_inclusion_probabilities():
    from src.classification.evaluation import evaluate
    ids = ['a', 'b']
    inputs = {jd: {'jd_id': jd, 'title': 'Developer', 'description': 'Build APIs and Build UI', 'requirements': ''} for jd in ids}
    annotations = [{'annotator': name, 'blind': True, 'guideline_version': 'v1', 'role': 'Backend'} for name in ('one', 'two')]
    gold = [{'jd_id': jd, 'role': 'Backend', 'seniority': 'unknown', 'ambiguous': False, 'multiple_roles': False,
             'annotations': annotations, 'adjudicated': True, 'adjudicator': 'one',
             'evidence': [{'target': 'primary_role', 'field': 'description', 'quote': 'Build APIs'}]} for jd in ids]
    correct = {**make_proposal(), 'jd_id': 'a'}
    incorrect = {**make_proposal(), 'jd_id': 'b', 'primary_role': 'Frontend',
                 'evidence': [{'target': 'primary_role', 'field': 'description', 'quote': 'Build UI'}]}
    predictions = [{'jd_id': jd, 'status': 'PROPOSED', 'suggested': proposal, 'validation_status': 'VALID'}
                   for jd, proposal in [('a', correct), ('b', incorrect)]]
    result = evaluate(predictions, gold, ids, 2, 2, inputs=inputs,
                      sampling_probabilities={'a': .5, 'b': .25}, unrepresented_groups=3)
    assert result['metrics']['Backend']['recall'] == .5
    weighted = result['weighted_group_estimates']
    assert weighted['metrics']['Backend']['recall'] == pytest.approx(1 / 3)
    assert weighted['accepted_precision'] == pytest.approx(1 / 3)
    assert weighted['estimated_input_groups'] == 6
    assert weighted['unrepresented_input_groups'] == 3
    assert not result['full_gate']
    with pytest.raises(ValueError, match='probabilities'):
        evaluate(predictions, gold, ids, 2, 2, inputs=inputs, sampling_probabilities={'a': 0, 'b': .25})
