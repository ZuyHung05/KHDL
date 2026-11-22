"""Transfer validated proposals only with exact provenance and submitted input equivalence."""
import json
from collections import defaultdict, Counter
import pyarrow.parquet as pq
import yaml
from .dataset import ROOT, payload, content_hash
from .validation import validate
from .runner import preflight
from src.collection.runner import sha256_file
from src.preparation.publish_curated import verify_release


def member_key(member):
    if 'source_locator' in member:
        loc = json.loads(member['source_locator'])
        return (member['source_id'], member['source_file'], member['snapshot_sha256'], loc['row_index'])
    return (member['source_id'], member['file'], member['sha256'], member['row_index'])


def decide(target, legacy, predictions, expected_versions, expected_files, legacy_manifest_hash):
    """Pure decision boundary. A missing/invalid member blocks whole-group transfer."""
    reasons = set()
    signatures, proposals, revisions = set(), [], set()
    target_hash = content_hash(payload(target))
    for record in legacy:
        prediction = predictions.get(record['jd_id'])
        if not prediction:
            reasons.add('no_prediction'); continue
        if prediction.get('status') == 'PENDING':
            reasons.add('pending'); continue
        if {member_key(m) for m in prediction.get('source_members', [])} != {member_key(m) for m in record.get('source_members', [])}: reasons.add('prediction_provenance_mismatch')
        proposal = prediction.get('suggested') or {}
        signatures.add(tuple(proposal.get(k) for k in ('primary_role', 'role_family', 'seniority')))
        if prediction.get('status') != 'PROPOSED' or proposal.get('review_required'):
            reasons.add('review_required')
        versions = prediction.get('versions', {})
        if any(versions.get(k) != v for k, v in expected_versions.items()): reasons.add('version_mismatch')
        if not versions.get('model_revision'): reasons.add('model_revision_missing')
        else: revisions.add(versions['model_revision'])
        if versions.get('corpus_manifest_sha256') != legacy_manifest_hash: reasons.add('legacy_manifest_mismatch')
        if any(versions.get('files_sha256', {}).get(k) != v for k, v in expected_files.items()): reasons.add('taxonomy_or_prompt_mismatch')
        if prediction.get('content_hash') != content_hash(payload(record)): reasons.add('legacy_input_hash_mismatch')
        if content_hash(payload(record)) != target_hash: reasons.add('target_input_hash_mismatch')
        try:
            checked = validate(proposal, payload(record))
            checked['jd_id'] = target['jd_id']
            validate(checked, payload(target))
            proposals.append(checked)
        except (ValueError, TypeError, KeyError): reasons.add('invalid_schema_or_evidence')
    if len(signatures) > 1: reasons.add('label_conflict')
    if len(revisions) > 1: reasons.add('model_revision_conflict')
    if not legacy: reasons.add('missing_provenance')
    if 'label_conflict' in reasons: status = 'conflict'
    elif 'pending' in reasons: status = 'pending'
    elif 'missing_provenance' in reasons: status = 'unmatched'
    elif reasons: status = 'blocked'
    else: status = 'transferred'
    return {'status': status, 'transferred': status == 'transferred', 'reasons': sorted(reasons),
            'suggested': proposals[0] if status == 'transferred' and proposals else None,
            'target_content_hash': target_hash}


def read_jsonl(path):
    with path.open(encoding='utf-8') as handle: return [json.loads(line) for line in handle if line.strip()]


def run():
    preflight('roles_v8'); preflight('m02_v1')
    release = ROOT/'data/curated/v1'; verify_release(release)
    base = ROOT/'data/curated/role_classification'
    oldbase = base/'corpora/roles_v8'; newbase = base/'corpora/m02_v1'
    require_hash = json.loads((newbase/'corpus_manifest.json').read_text())['m02_manifest_sha256']
    if sha256_file(release/'manifest.json') != require_hash: raise ValueError('Target release mismatch')
    corpus = read_jsonl(oldbase/'corpus.jsonl')
    target = {r['jd_id']: r for r in read_jsonl(newbase/'corpus.jsonl')}
    prediction_path = base/'runs/gemini_full_v1/predictions.jsonl'
    prediction_hash = sha256_file(prediction_path)
    predrows = read_jsonl(prediction_path)
    predictions = {r['jd_id']: r for r in predrows}
    if len(predictions) != len(predrows): raise ValueError('Duplicate prediction IDs')
    index = defaultdict(set); legacy = {r['jd_id']: r for r in corpus}
    for r in corpus:
        for m in r['source_members']: index[member_key(m)].add(r['jd_id'])
    groups = defaultdict(list)
    for m in pq.read_table(release/'duplicate_mapping.parquet').to_pylist(): groups[m['jd_id']].append(m)
    config = yaml.safe_load((ROOT/'configs/gemini_roles.yaml').read_text())
    versions = {k: config[k] for k in ('model','prompt_version','schema_version','preprocessing_version','temperature')}
    files = {p: sha256_file(ROOT/p) for p in ('configs/role_taxonomy.yaml','configs/role_definitions.yaml','prompts/role_classification_v1.txt')}
    results = []
    for gid, members in sorted(groups.items()):
        keys = {member_key(m) for m in members}; ids = set().union(*(index[k] for k in keys))
        missing = any(len(index[k]) != 1 for k in keys)
        result = decide(target[gid], [legacy[i] for i in sorted(ids)], predictions, versions, files, sha256_file(oldbase/'corpus_manifest.json'))
        if missing:
            result.update(status='unmatched', transferred=False, suggested=None)
            result['reasons'].append('missing_or_ambiguous_member_provenance')
        result.update(legacy_versions={lid: predictions[lid].get('versions') for lid in ids if lid in predictions},m02_jd_id=gid, legacy_ids=sorted(ids), record_ids=sorted(m['record_id'] for m in members))
        results.append(result)
    if sha256_file(prediction_path) != prediction_hash: raise ValueError('Predictions changed during reconciliation; retry later')
    out = ROOT/'data/reconciliation'; out.mkdir(exist_ok=True)
    with (out/'roles_v8_to_m02_v1.jsonl').open('w') as f:
        for r in results: f.write(json.dumps(r, ensure_ascii=False)+'\n')
    transferred = {r['m02_jd_id'] for r in results if r['transferred']}
    candidates = read_jsonl(newbase/'candidates.jsonl')
    for filename, records in [('transferred_predictions.jsonl',[r for r in results if r['transferred']]), ('remaining_candidates.jsonl',[r for r in candidates if r['jd_id'] not in transferred])]:
        with (out/filename).open('w') as f:
            for record in records: f.write(json.dumps(record,ensure_ascii=False)+'\n')
    report = {'target_candidates':len(candidates),'remaining_candidates':sum(r['jd_id'] not in transferred for r in candidates),'groups': len(results), 'provenance_matched': sum(r['status'] != 'unmatched' for r in results), 'statuses': {name:sum(r['status']==name for r in results) for name in ('transferred','conflict','pending','blocked','unmatched')},
              'transferred': sum(r['transferred'] for r in results),
              'reasons': dict(Counter(reason for r in results for reason in r['reasons'])),
              'legacy_predictions_sha256': sha256_file(base/'runs/gemini_full_v1/predictions.jsonl'),
              'target_manifest_sha256': sha256_file(newbase/'corpus_manifest.json'),
              'note': 'Separate suggested labels only; exact submitted-text hash and version/evidence checks; not gold.'}
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n'); print(json.dumps(report, indent=2))

if __name__ == '__main__': run()
