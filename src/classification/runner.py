"""Prepare and inspect the role-classification corpus offline."""
import argparse
import json
import re
from pathlib import Path
from .dataset import OUT, ROOT, prepare, payload, content_hash, audit_samples
from src.collection.runner import sha256_file


def preflight(corpus_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', corpus_id):
        raise ValueError('Invalid corpus ID')
    base = OUT / corpus_id
    manifest = json.loads((base / 'corpus_manifest.json').read_text(encoding='utf-8'))
    if manifest['corpus_id'] != corpus_id:
        raise ValueError('Corpus ID mismatch')
    artifact_hashes = manifest.get('artifacts_sha256', {})
    if artifact_hashes and set(artifact_hashes) != {'corpus.jsonl', 'candidates.jsonl', 'samples.json'}:
        raise ValueError('Frozen corpus artifact hash list is incomplete')
    for name, expected_hash in artifact_hashes.items():
        if name not in ('corpus.jsonl', 'candidates.jsonl', 'samples.json') or sha256_file(base / name) != expected_hash:
            raise ValueError('Frozen corpus artifact checksum mismatch')
    if sha256_file(ROOT / 'configs/role_taxonomy.yaml') != manifest['taxonomy_sha256']:
        raise ValueError('Taxonomy changed since corpus preparation')
    for entry in manifest['snapshots']:
        root = (ROOT / 'data/raw').resolve()
        path = (root / entry['source_id'] / entry['snapshot'] / Path(entry['source_file']).name).resolve()
        if not path.is_relative_to(root) or sha256_file(path) != entry['file_sha256']:
            raise ValueError('Snapshot missing or checksum mismatch')
    def read_records(name):
        with (base / name).open(encoding='utf-8') as handle:
            return [json.loads(line) for line in handle if line.strip()]
    records = read_records('corpus.jsonl')
    candidates = read_records('candidates.jsonl')
    ids = [item['jd_id'] for item in records]
    if len(ids) != len(set(ids)) or len(records) != manifest['total']:
        raise ValueError('Corpus count or IDs do not match manifest')
    counts = {status: sum(item['rule_status'] == status for item in records)
              for status in ('classified', 'unknown', 'needs_review')}
    expected = [item for item in records if item['rule_status'] in ('unknown', 'needs_review')]
    if counts != manifest['counts'] or candidates != expected or any(not item.get('source_members') for item in records):
        raise ValueError('Corpus counts, provenance or candidates are inconsistent')
    if manifest.get('artifacts_sha256') and any(item.get('content_hash') != content_hash(payload(item)) for item in records):
        raise ValueError('Classification input hash mismatch')
    if manifest.get('preprocessing_version') and any(item.get('preprocessing_version', 'nfc_redact_v2') != manifest['preprocessing_version'] for item in records):
        raise ValueError('Record preprocessing version differs from corpus manifest')
    sample_audit = None
    if 'samples.json' in manifest.get('artifacts_sha256', {}):
        sample_audit = audit_samples(candidates, json.loads((base / 'samples.json').read_text(encoding='utf-8')))
    return {'corpus_id': corpus_id, 'status': 'OFFLINE_OK', 'total': len(records),
            'counts': counts, 'candidates': len(candidates), 'snapshots_verified': len(manifest['snapshots']),
            'artifact_hashes_verified': bool(manifest.get('artifacts_sha256')),
            'sample_audit': sample_audit,
            'note': 'Offline integrity checks only; API, quota, privacy review and pilot gates not verified.'}


def export_sample(corpus_id, stage):
    """Write the exact redacted payloads for local manual review, without network access."""
    preflight(corpus_id)
    base = OUT / corpus_id
    manifest = json.loads((base / 'corpus_manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('artifacts_sha256'):
        raise ValueError('Prepare a new frozen corpus with versioned payloads and samples')
    samples = json.loads((base / 'samples.json').read_text(encoding='utf-8'))['stages'][stage]
    selected = {sample['jd_id'] for sample in samples}
    with (base / 'candidates.jsonl').open(encoding='utf-8') as handle:
        records = {item['jd_id']: item for item in map(json.loads, handle) if item['jd_id'] in selected}
    if len(records) != len(samples):
        raise ValueError('Sample refers to missing or duplicate candidates')
    path = base / (stage + '_payload_review.jsonl')
    if path.exists():
        raise FileExistsError('Review export already exists; preserve or remove it deliberately')
    with path.open('x', encoding='utf-8') as handle:
        for sample in samples:
            item = payload(records[sample['jd_id']])
            if content_hash(item) != sample['content_hash']:
                raise ValueError('Sample input hash changed')
            handle.write(json.dumps(item, ensure_ascii=False) + '\n')
    return {'stage': stage, 'records': len(samples), 'review_file': str(path),
            'note': 'Sensitive local data; automatic redaction is not a guarantee of anonymity.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    p = subs.add_parser('prepare'); p.add_argument('--corpus-id', required=True)
    p = subs.add_parser('preflight'); p.add_argument('--corpus', required=True); p.add_argument('--dry-run', action='store_true', required=True)
    p = subs.add_parser('export-sample'); p.add_argument('--corpus', required=True); p.add_argument('--stage', choices=('smoke50', 'pilot200'), required=True)
    p = subs.add_parser('pilot'); p.add_argument('--corpus', required=True); p.add_argument('--stage', choices=('pilot5', 'smoke50', 'pilot200'), required=True); p.add_argument('--run-id', required=True); p.add_argument('--privacy-reviewed', action='store_true'); p.add_argument('--smoke-review')
    p = subs.add_parser('resume'); p.add_argument('--run-id', required=True)
    p = subs.add_parser('full'); p.add_argument('--corpus', required=True); p.add_argument('--run-id', required=True); p.add_argument('--gate-run'); p.add_argument('--confirm-full', action='store_true'); p.add_argument('--privacy-reviewed', action='store_true')
    p = subs.add_parser('report'); p.add_argument('--run-id', required=True)
    p = subs.add_parser('evaluate'); p.add_argument('--run-id', required=True); p.add_argument('--gold', required=True); p.add_argument('--development-set', action='store_true'); p.add_argument('--cloud-case-run'); p.add_argument('--cloud-case-gold')
    args = parser.parse_args()
    if args.command == 'prepare':
        print(json.dumps(prepare(args.corpus_id), ensure_ascii=False, indent=2))
    elif args.command == 'preflight':
        print(json.dumps(preflight(args.corpus), ensure_ascii=False, indent=2))
    elif args.command == 'export-sample':
        print(json.dumps(export_sample(args.corpus, args.stage), ensure_ascii=False, indent=2))
    elif args.command == 'pilot':
        from .workflow import start_run
        print(json.dumps(start_run(args.corpus, args.stage, args.run_id, args.privacy_reviewed, preflight, args.smoke_review), ensure_ascii=False, indent=2))
    elif args.command == 'resume':
        from .workflow import resume_run
        print(json.dumps(resume_run(args.run_id, preflight), ensure_ascii=False, indent=2))
    elif args.command == 'full':
        from .workflow import start_run
        print(json.dumps(start_run(args.corpus, 'full', args.run_id, args.privacy_reviewed, preflight, gate_run=args.gate_run, confirm_full=args.confirm_full), ensure_ascii=False, indent=2))
    else:
        from .workflow import BASE, check_id
        from .state import State
        run_id = check_id(args.run_id)
        state = State(BASE / 'state.sqlite')
        try:
            row = state.db.execute('SELECT manifest FROM runs WHERE run_id=?', (run_id,)).fetchone()
            if not row:
                raise ValueError('Unknown run')
            manifest = json.loads(row[0])
            preflight(manifest['corpus_id'])
            run_dir = BASE / 'runs' / run_id
            if args.command == 'report':
                from .workflow import summarize, export_run, read_records
                from .reporting import report_run
                run_status = state.db.execute('SELECT status FROM runs WHERE run_id=?', (run_id,)).fetchone()[0]
                if run_status == 'RUNNING':
                    raise ValueError('Wait for the run to stop before generating reports')
                all_records = {item['jd_id']: item for item in read_records(OUT / manifest['corpus_id'] / 'candidates.jsonl')}
                export_run(state, run_id, [all_records[jd] for jd in manifest['selected_jd_ids']])
                result = report_run(run_id, run_dir, manifest, summarize(state, run_id))
            else:
                from .evaluation import evaluate, read_jsonl, plot_confusion
                if manifest['stage'] != 'pilot200':
                    raise ValueError('Only an independent pilot200 can be evaluated for the full gate')
                received, valid = state.db.execute("SELECT COUNT(DISTINCT jd_id), COUNT(DISTINCT CASE WHEN status='VALID' THEN jd_id END) FROM attempts WHERE run_id=? AND status IN ('VALID','INVALID_RESPONSE','MODEL_CHANGED','REFUSAL')", (run_id,)).fetchone()
                frozen_records = read_jsonl(OUT / manifest['corpus_id'] / 'candidates.jsonl')
                inputs = {item['jd_id']: payload(item) for item in frozen_records if item['jd_id'] in set(manifest['selected_jd_ids'])}
                if bool(args.cloud_case_run) != bool(args.cloud_case_gold):
                    raise ValueError('Provide both --cloud-case-run and --cloud-case-gold')
                external_cloud = suite = None
                if args.cloud_case_run:
                    from .workflow import read_cloud_suite
                    external_cloud, suite = read_cloud_suite(state, manifest, args.cloud_case_run, args.cloud_case_gold)
                from .workflow import verified_predictions
                samples = json.loads((OUT / manifest['corpus_id'] / 'samples.json').read_text(encoding='utf-8'))
                sampling_audit = audit_samples(frozen_records, samples)
                probabilities = {item['jd_id']: item['group_inclusion_probability'] for item in samples['stages']['pilot200']}
                result = evaluate(verified_predictions(state, run_id, manifest, run_dir), read_jsonl(args.gold), manifest['selected_jd_ids'], received, valid or 0, args.development_set, inputs, external_cloud, probabilities, sampling_audit['unrepresented_groups'])
                result['sampling_audit'] = sampling_audit
                result['cloud_suite'] = suite
                result['gold_path'] = str(Path(args.gold).resolve())
                result['gold_sha256'] = sha256_file(Path(args.gold))
                result['predictions_sha256'] = sha256_file(run_dir / 'predictions.jsonl')
                result['run_manifest_sha256'] = sha256_file(run_dir / 'run_manifest.json')
                result['evaluation_code_sha256'] = sha256_file(ROOT / 'src/classification/evaluation.py')
                dest = run_dir / 'reports'; dest.mkdir(parents=True, exist_ok=True)
                (dest / 'evaluation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                plot_confusion(result, dest / 'confusion_matrix.png')
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            state.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
