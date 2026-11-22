"""Create and resume sequential runs against a frozen corpus."""
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
import yaml

from .dataset import ROOT, OUT, payload, content_hash
from .engine import classify_one, has_job_text, StopRun
from .gemini_client import load_client
from .quota import QuotaPaused, RateWait, reserve, validate_limits
from .state import State, cache_key, canonical, project_lock
from .validation import evidence_offsets
from src.collection.runner import sha256_file

BASE = ROOT / 'data/curated/role_classification'


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def check_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid identifier')
    return value


def verified_revision(state, run_id, config, client):
    """Count model metadata requests against the same conservative request budget."""
    while True:
        try:
            reserve(state, run_id, config['quota'], 0, kind='model_metadata')
            break
        except RateWait as exc:
            time.sleep(exc.seconds)
    try:
        return client.model_revision()
    except Exception:
        raise StopRun('Cannot verify requested model and credentials; no generation request sent') from None


def read_records(path):
    with path.open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def verified_predictions(state, run_id, manifest, run_dir):
    """Reject exported predictions that differ from the authoritative checkpoint."""
    rows = read_records(run_dir / 'predictions.jsonl')
    by_id = {row['jd_id']: row for row in rows}
    tasks = state.db.execute('SELECT jd_id,status,result,cache_hit FROM tasks WHERE run_id=?', (run_id,)).fetchall()
    if (len(by_id) != len(rows) or set(by_id) != set(manifest['selected_jd_ids']) or
            set(by_id) != {row[0] for row in tasks}):
        raise ValueError('Prediction IDs do not match the checkpoint')
    for jd, status, raw, cache_hit in tasks:
        data = json.loads(raw) if raw else None
        proposal = data if data and 'primary_role' in data else None
        exported = by_id[jd]
        if (exported.get('status') != status or exported.get('suggested') != proposal or
                exported.get('validation_status') != ('VALID' if proposal else None) or
                exported.get('cache_hit') != bool(cache_hit)):
            raise ValueError('Prediction differs from the authoritative checkpoint')
    return rows


def selected_sample(corpus, stage):
    base = OUT / check_id(corpus)
    samples = json.loads((base / 'samples.json').read_text(encoding='utf-8'))['stages']
    records = {r['jd_id']: r for r in read_records(base / 'candidates.jsonl')}
    if stage == 'pilot5':
        selected, sources = [], set()
        for entry in samples['smoke50']:
            if entry['source_id'] not in sources and has_job_text(payload(records[entry['jd_id']])):
                selected.append(entry)
                sources.add(entry['source_id'])
                if len(selected) == 5:
                    break
        if len(selected) != 5:
            raise ValueError('Five independent source examples are unavailable')
    elif stage in ('smoke50', 'pilot200'):
        selected = samples[stage]
    elif stage == 'full':
        return list(records.values())
    else:
        raise ValueError('Unsupported stage')
    return [records[x['jd_id']] for x in selected]


def version_parts(corpus, config, model, model_revision):
    base = OUT / corpus
    files = ['prompts/role_classification_v1.txt', 'configs/role_definitions.yaml',
             'configs/role_taxonomy.yaml', 'src/classification/schema.py',
             'src/classification/dataset.py', 'src/classification/validation.py',
             'src/classification/rules.py', 'src/collection/runner.py',
             'src/classification/gemini_client.py', 'src/classification/engine.py',
             'src/classification/quota.py', 'src/classification/workflow.py', 'src/classification/state.py']
    hashes = {name: sha256_file(ROOT / name) for name in files}
    return {'corpus_manifest_sha256': sha256_file(base / 'corpus_manifest.json'),
            'files_sha256': hashes, 'model': model, 'model_revision': model_revision,
            'prompt_version': config['prompt_version'], 'schema_version': config['schema_version'],
            'preprocessing_version': config['preprocessing_version'], 'temperature': config['temperature']}


def key_for(item, versions):
    # Corpus ID and JD ID are deliberately absent: identical content can share cache.
    return cache_key({'content_hash': content_hash(item), 'model': versions['model'],
                      'model_revision': versions['model_revision'], 'prompt_version': versions['prompt_version'],
                      'schema_version': versions['schema_version'], 'preprocessing_version': versions['preprocessing_version'],
                      'source_hashes': versions['files_sha256'], 'temperature': versions['temperature']})


def verify_smoke_review(state, corpus, review_path):
    if not review_path:
        raise ValueError('Pilot 200 requires a documented manual smoke50 review')
    review = json.loads(Path(review_path).read_text(encoding='utf-8'))
    smoke_id = check_id(review.get('run_id', ''))
    row = state.db.execute('SELECT manifest,status FROM runs WHERE run_id=?', (smoke_id,)).fetchone()
    if not row:
        raise ValueError('Smoke run not found')
    smoke = json.loads(row[0])
    if row[1] != 'COMPLETED' or smoke['stage'] != 'smoke50' or smoke['corpus_id'] != corpus or not smoke.get('actual_model_version'):
        raise ValueError('Smoke run must be complete and use the same corpus')
    tasks = state.db.execute('SELECT jd_id,status FROM tasks WHERE run_id=?', (smoke_id,)).fetchall()
    if len(tasks) != 50 or any(status not in ('PROPOSED', 'REVIEW_REQUIRED') for _, status in tasks):
        raise ValueError('All 50 smoke tasks must be resolved or sent to review')
    reviewed = review.get('reviewed_jd_ids', [])
    if not review.get('reviewer') or review.get('all_reviewed') is not True or review.get('prompt_frozen') is not True or len(reviewed) != 50 or set(reviewed) != {jd for jd, _ in tasks}:
        raise ValueError('Smoke review must attest to each sample and a frozen prompt')
    return smoke


def read_cloud_suite(state, pilot, case_run_id, gold_path):
    """Verify an independent counterexample suite against frozen run outputs."""
    from .evaluation import assess_cloud_counterexamples, read_jsonl
    case_run_id = check_id(case_run_id or '')
    row = state.db.execute('SELECT manifest,status FROM runs WHERE run_id=?', (case_run_id,)).fetchone()
    if not row:
        raise ValueError('Cloud counterexample run not found')
    case_run = json.loads(row[0])
    if (row[1] != 'COMPLETED' or case_run['corpus_id'] != pilot['corpus_id'] or
            case_run['versions'] != pilot['versions'] or not case_run.get('actual_model_version') or
            case_run['actual_model_version'] != pilot.get('actual_model_version')):
        raise ValueError('Cloud test run must be complete and use the same frozen model and corpus')
    gold = read_jsonl(gold_path)
    ids = {row['jd_id'] for row in gold}
    if not ids or not ids.issubset(set(case_run['selected_jd_ids'])):
        raise ValueError('Cloud test gold must refer to cases selected in its own run')
    if case_run_id == pilot['run_id'] or ids.intersection(pilot['selected_jd_ids']):
        raise ValueError('Cloud counterexample cases must be independent of the pilot sample')
    run_dir = BASE / 'runs' / case_run_id
    predictions = [row for row in verified_predictions(state, case_run_id, case_run, run_dir) if row['jd_id'] in ids]
    records = read_records(OUT / pilot['corpus_id'] / 'candidates.jsonl')
    hashes = {record['jd_id']: record['content_hash'] for record in records}
    if {hashes[jd] for jd in ids}.intersection(hashes[jd] for jd in pilot['selected_jd_ids']):
        raise ValueError('Cloud counterexample inputs must not overlap pilot content')
    inputs = {record['jd_id']: payload(record) for record in records if record['jd_id'] in ids}
    result = assess_cloud_counterexamples(predictions, gold, inputs)
    evidence = {'run_id': case_run_id, 'gold_path': str(Path(gold_path).resolve()),
                'gold_sha256': sha256_file(Path(gold_path)),
                'predictions_sha256': sha256_file(run_dir / 'predictions.jsonl'),
                'run_manifest_sha256': sha256_file(run_dir / 'run_manifest.json')}
    return result, evidence


def verify_pilot_gate(state, corpus, gate_run):
    from .evaluation import evaluate, read_jsonl
    from .dataset import audit_samples
    gate_run = check_id(gate_run or '')
    row = state.db.execute('SELECT manifest,status FROM runs WHERE run_id=?', (gate_run,)).fetchone()
    if not row:
        raise ValueError('Pilot gate run not found')
    pilot = json.loads(row[0]); run_dir = BASE / 'runs' / gate_run
    if row[1] != 'COMPLETED' or pilot['stage'] != 'pilot200' or pilot['corpus_id'] != corpus:
        raise ValueError('A complete independent pilot200 from the same corpus is required')
    evaluation = json.loads((run_dir / 'reports/evaluation.json').read_text(encoding='utf-8'))
    checks = [(Path(evaluation['gold_path']), evaluation['gold_sha256']),
              (run_dir / 'predictions.jsonl', evaluation['predictions_sha256']),
              (run_dir / 'run_manifest.json', evaluation['run_manifest_sha256']),
              (ROOT / 'src/classification/evaluation.py', evaluation['evaluation_code_sha256'])]
    if any(sha256_file(path) != expected for path, expected in checks):
        raise ValueError('Pilot evaluation evidence changed; re-evaluate')
    records = read_records(OUT / corpus / 'candidates.jsonl')
    samples = json.loads((OUT / corpus / 'samples.json').read_text(encoding='utf-8'))
    sampling = audit_samples(records, samples)
    probabilities = {item['jd_id']: item['group_inclusion_probability'] for item in samples['stages']['pilot200']}
    ids = set(pilot['selected_jd_ids'])
    inputs = {record['jd_id']: payload(record) for record in records if record['jd_id'] in ids}
    received, valid = state.db.execute("SELECT COUNT(DISTINCT jd_id), COUNT(DISTINCT CASE WHEN status='VALID' THEN jd_id END) FROM attempts WHERE run_id=? AND status IN ('VALID','INVALID_RESPONSE','MODEL_CHANGED','REFUSAL')", (gate_run,)).fetchone()
    external_cloud = None
    if evaluation.get('cloud_suite'):
        suite = evaluation['cloud_suite']
        external_cloud, actual_evidence = read_cloud_suite(state, pilot, suite['run_id'], suite['gold_path'])
        if actual_evidence != suite:
            raise ValueError('Cloud counterexample evidence changed; re-evaluate')
    checked = evaluate(verified_predictions(state, gate_run, pilot, run_dir), read_jsonl(evaluation['gold_path']),
                       pilot['selected_jd_ids'], received, valid or 0, False, inputs, external_cloud,
                       probabilities, sampling['unrepresented_groups'])
    if not evaluation.get('full_gate') or not checked['full_gate']:
        raise ValueError('Pilot quality gate did not pass')
    return pilot, checked


def start_run(corpus, stage, run_id, privacy_reviewed, preflight, smoke_review=None,
              gate_run=None, confirm_full=False):
    check_id(run_id)
    info = preflight(corpus)
    if not info['artifact_hashes_verified']:
        raise ValueError('A fully frozen corpus is required')
    base = OUT / corpus
    config = yaml.safe_load((ROOT / 'configs/gemini_roles.yaml').read_text(encoding='utf-8'))
    validate_limits(config['quota'])
    frozen = json.loads((base / 'corpus_manifest.json').read_text(encoding='utf-8'))
    if frozen.get('preprocessing_version') != config['preprocessing_version']:
        raise ValueError('Corpus preprocessing version differs from configuration')
    records = selected_sample(corpus, stage)
    if stage == 'full' and not confirm_full:
        raise ValueError('Full classification requires explicit --confirm-full authorization')
    load_dotenv(ROOT / '.env', override=False)
    model = os.getenv('GEMINI_MODEL') or config['model']
    if model != 'gemini-3.5-flash-lite':
        raise ValueError('Set GEMINI_MODEL to gemini-3.5-flash-lite')
    if not model or not re.fullmatch(r'[A-Za-z0-9_.\-/]+', model):
        raise ValueError('Invalid GEMINI_MODEL')
    with project_lock(BASE / 'project.lock'):
        state = State(BASE / 'state.sqlite')
        try:
            smoke = verify_smoke_review(state, corpus, smoke_review) if stage == 'pilot200' else None
            pilot, evaluation = None, None
            if state.db.execute('SELECT 1 FROM runs WHERE run_id=?', (run_id,)).fetchone():
                raise ValueError('Run ID already exists; use resume')
            run_dir = BASE / 'runs' / run_id
            if run_dir.exists():
                raise ValueError('Run directory already exists; choose another run ID')
            predecessor = pilot or smoke
            if predecessor and version_parts(corpus, config, model, predecessor['versions']['model_revision']) != predecessor['versions']:
                raise ValueError('Frozen model, code, prompt or taxonomy differs from the prior run')
            client = load_client(model, config['request_timeout_seconds'])
            revision = verified_revision(state, run_id, config, client)
            versions = version_parts(corpus, config, model, revision)
            if smoke and smoke['versions'] != versions:
                raise ValueError('Pilot must use the same frozen model, code, prompt and taxonomy as smoke')
            if pilot and pilot['versions'] != versions:
                raise ValueError('Full run must use the same frozen model, code, prompt and taxonomy as pilot')
            manifest = {'run_id': run_id, 'corpus_id': corpus, 'stage': stage, 'created_at': utc_now(),
                        'versions': versions, 'config': config, 'privacy_reviewed': False,
                        'privacy_review_export_sha256': None,
                        'smoke_review_sha256': sha256_file(Path(smoke_review)) if smoke_review else None,
                        'gate_run': gate_run, 'cloud_requires_review': evaluation['cloud_requires_review'] if evaluation else True,
                        'selected_jd_ids': [r['jd_id'] for r in records], 'actual_model_version': None,
                        'expected_model_version': (pilot or smoke or {}).get('actual_model_version'),
                        'note': 'Provider alias may change without an immutable version. External project usage is not available locally.'}
            tasks = [(r['jd_id'], key_for(payload(r), versions)) for r in records]
            state.create_run(run_id, manifest, tasks)
            run_dir.mkdir(parents=True, exist_ok=False)
            write_json(run_dir / 'run_manifest.json', manifest)
            return execute(state, client, manifest, records)
        finally:
            state.close()


def resume_run(run_id, preflight):
    check_id(run_id)
    with project_lock(BASE / 'project.lock'):
        state = State(BASE / 'state.sqlite')
        try:
            row = state.db.execute('SELECT manifest FROM runs WHERE run_id=?', (run_id,)).fetchone()
            if not row:
                raise ValueError('Unknown run')
            manifest = json.loads(row[0]); corpus = manifest['corpus_id']
            preflight(corpus)
            config = yaml.safe_load((ROOT / 'configs/gemini_roles.yaml').read_text(encoding='utf-8'))
            if config != manifest['config']:
                raise ValueError('Run configuration changed; create a new run')
            load_dotenv(ROOT / '.env', override=False)
            if os.getenv('GEMINI_MODEL', config['model']) != manifest['versions']['model']:
                raise ValueError('Requested model changed; create a new run')
            if version_parts(corpus, config, manifest['versions']['model'], manifest['versions']['model_revision']) != manifest['versions']:
                raise ValueError('Corpus, code, prompt or taxonomy changed; create a new run')
            unfinished = state.db.execute("SELECT COUNT(*) FROM tasks WHERE run_id=? AND status IN ('PENDING','RUNNING','RETRY_WAIT','FAILED')", (run_id,)).fetchone()[0]
            if not unfinished:
                return summarize(state, run_id)
            client = load_client(manifest['versions']['model'], config['request_timeout_seconds'])
            revision = verified_revision(state, run_id, config, client)
            if version_parts(corpus, config, manifest['versions']['model'], revision) != manifest['versions']:
                raise ValueError('Corpus, code, prompt, taxonomy or model version changed; create a new run')
            records = {r['jd_id']: r for r in read_records(OUT / corpus / 'candidates.jsonl')}
            state.recover(run_id)
            return execute(state, client, manifest, [records[jd] for jd in manifest['selected_jd_ids']])
        finally:
            state.close()


def write_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def execute(state, client, manifest, records):
    run_id = manifest['run_id']; actual = manifest.get('actual_model_version'); status = 'COMPLETED'
    with state.db:
        state.db.execute("UPDATE runs SET status='RUNNING' WHERE run_id=?", (run_id,))
    try:
        processed = 0
        for record in records:
            row = state.db.execute('SELECT status,cache_key FROM tasks WHERE run_id=? AND jd_id=?', (run_id, record['jd_id'])).fetchone()
            if row[0] != 'PENDING':
                continue
            actual = classify_one(state, run_id, payload(record), row[1], client, manifest['config']['quota'], actual,
                                  manifest['config']['max_input_characters'], cloud_requires_review=manifest.get('cloud_requires_review', True),
                                  expected_model_version=manifest.get('expected_model_version'))
            processed += 1
            if processed % 50 == 0:
                export_run(state, run_id, records)
        if state.db.execute("SELECT COUNT(*) FROM tasks WHERE run_id=? AND status IN ('FAILED','PENDING','RUNNING','RETRY_WAIT')", (run_id,)).fetchone()[0]:
            status = 'COMPLETED_WITH_ERRORS'
    except QuotaPaused:
        status = 'QUOTA_PAUSED'
    except StopRun:
        status = 'STOPPED'
        raise
    except BaseException:
        status = 'INTERRUPTED'
        raise
    finally:
        with state.db:
            state.db.execute('UPDATE runs SET status=? WHERE run_id=?', (status, run_id))
        export_run(state, run_id, records)
    return summarize(state, run_id)


def summarize(state, run_id):
    statuses = dict(state.db.execute('SELECT status, COUNT(*) FROM tasks WHERE run_id=? GROUP BY status', (run_id,)))
    attempts = state.db.execute('SELECT status, usage FROM attempts WHERE run_id=?', (run_id,)).fetchall()
    usage = [json.loads(x[1]) if x[1] else {'unknown_usage': True} for x in attempts]
    totals = {}
    for key in ('prompt_token_count', 'candidates_token_count', 'thoughts_token_count', 'cached_content_token_count', 'total_token_count'):
        observed = [x[key] for x in usage if x.get(key) is not None]
        totals[key] = sum(observed) if observed else None
    reserved = dict(state.db.execute('SELECT kind, COUNT(*) FROM quota_requests WHERE run_id=? GROUP BY kind', (run_id,)))
    manifest_row = state.db.execute('SELECT manifest FROM runs WHERE run_id=?', (run_id,)).fetchone()
    manifest = json.loads(manifest_row[0])
    quota = manifest.get('config', {}).get('quota', {})
    zero_rate_confirmed = quota.get('tier') == 'free' and quota.get('zero_rate_confirmed') is True
    return {'run_id': run_id, 'status': state.db.execute('SELECT status FROM runs WHERE run_id=?', (run_id,)).fetchone()[0],
            'tasks': statuses, 'api_calls': len(attempts), 'unknown_usage': sum(bool(x.get('unknown_usage')) for x in usage),
            'quota_requests_by_kind': reserved,
            'usage_observed': totals, 'estimated_cost': 0 if zero_rate_confirmed else None,
            'cost_basis': ('Confirmed zero token rate for declared Free Tier; not billing data' if zero_rate_confirmed
                           else 'Unknown: the model-specific token rate has not been confirmed'),
            'external_project_usage': 'unknown; only this local database is counted'}


def export_run(state, run_id, records):
    run_dir = BASE / 'runs' / run_id; run_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(state.db.execute('SELECT manifest FROM runs WHERE run_id=?', (run_id,)).fetchone()[0])
    by_id = {r['jd_id']: r for r in records}
    rows = []
    query = state.db.execute('SELECT jd_id,status,result,cache_hit,attempts FROM tasks WHERE run_id=? ORDER BY rowid', (run_id,))
    for jd, status, result, hit, attempts in query:
        rec = by_id[jd]; result = json.loads(result) if result else None
        proposal = result if result and 'primary_role' in result else None
        request_attempts = state.db.execute('SELECT COUNT(*) FROM attempts WHERE run_id=? AND jd_id=?', (run_id, jd)).fetchone()[0]
        rows.append({'jd_id': jd, 'status': status, 'suggested': proposal, 'reason': result.get('reason') if result and not proposal else None,
                     'baseline': {'status': rec['rule_status'], 'role': rec['rule_primary_role']},
                     'content_hash': content_hash(payload(rec)), 'source_members': rec['source_members'],
                     'versions': manifest['versions'], 'actual_model_version': manifest.get('actual_model_version'),
                     'cache_hit': bool(hit), 'attempt': request_attempts, 'validation_status': 'VALID' if proposal else None,
                     'evidence_offsets': evidence_offsets(proposal, payload(rec)) if proposal else []})
    def write_lines(path, values):
        temp = path.with_suffix(path.suffix + '.tmp')
        with temp.open('w', encoding='utf-8') as handle:
            for value in values: handle.write(json.dumps(value, ensure_ascii=False) + '\n')
        temp.replace(path)
    write_lines(run_dir / 'predictions.jsonl', rows)
    write_lines(run_dir / 'review_queue.jsonl', [x for x in rows if x['status'] in ('REVIEW_REQUIRED', 'FAILED')])
    events = [{'jd_id': jd, 'stage': 'request', 'status': status, 'error_code': code, 'latency_ms': latency,
               'usage': json.loads(usage) if usage else {'unknown_usage': True}, 'timestamp': started}
              for jd, status, code, latency, usage, started in state.db.execute('SELECT jd_id,status,error_code,latency_ms,usage,started_at FROM attempts WHERE run_id=? ORDER BY id', (run_id,))]
    write_lines(run_dir / 'events.jsonl', events)
    write_json(run_dir / 'usage_summary.json', summarize(state, run_id))
    write_json(run_dir / 'run_manifest.json', manifest)
