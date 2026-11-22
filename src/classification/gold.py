"""Blind annotation templates and human-adjudication drafts for the pilot."""
import json
import shutil
import tempfile
from pathlib import Path

import yaml

from .dataset import ROOT, OUT, payload, content_hash
from .validation import SENIORITY, SPECIAL
from src.collection.runner import sha256_file

AUDIT = ROOT / 'data/audit/gemini_roles'


def _read_jsonl(path):
    with Path(path).open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path, rows):
    with path.open('x', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def frozen_pilot(corpus_id, preflight):
    info = preflight(corpus_id)
    if not info['artifact_hashes_verified']:
        raise ValueError('A fully frozen corpus is required')
    base = OUT / corpus_id
    samples = json.loads((base / 'samples.json').read_text(encoding='utf-8'))['stages']['pilot200']
    records = {row['jd_id']: row for row in _read_jsonl(base / 'candidates.jsonl')}
    jobs = []
    for sample in samples:
        item = payload(records[sample['jd_id']])
        if content_hash(item) != sample['content_hash']:
            raise ValueError('Frozen pilot input changed')
        jobs.append(item)
    return jobs


def create_templates(corpus_id, preflight):
    jobs = frozen_pilot(corpus_id, preflight)
    target = AUDIT / corpus_id
    AUDIT.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError('Annotation directory already exists')
    staging = Path(tempfile.mkdtemp(prefix='.gold-', dir=AUDIT))
    try:
        for label in ('annotator_a', 'annotator_b'):
            rows = [{**item, 'annotation': {'annotator': None, 'blind': None, 'guideline_version': 'v1',
                    'role': None, 'seniority': None, 'ambiguous': None, 'multiple_roles': None,
                    'evidence': []}} for item in jobs]
            _write_jsonl(staging / (label + '.jsonl'), rows)
        manifest = {'corpus_id': corpus_id, 'corpus_manifest_sha256': sha256_file(OUT / corpus_id / 'corpus_manifest.json'),
                    'samples_sha256': sha256_file(OUT / corpus_id / 'samples.json'), 'sample_count': len(jobs),
                    'note': 'Blank independent templates; no model predictions or inferred gold.'}
        (staging / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {'corpus_id': corpus_id, 'sample_count': len(jobs), 'directory': str(target),
            'note': 'Contains redacted job text; give the two files to independent annotators without model outputs.'}


def _validate_annotation(row, item, allowed_roles):
    if {k: row.get(k) for k in ('jd_id', 'title', 'description', 'requirements')} != item:
        raise ValueError('Annotation input differs from the frozen pilot payload')
    ann = row.get('annotation')
    if not isinstance(ann, dict) or not isinstance(ann.get('annotator'), str) or not ann['annotator'].strip() or ann.get('blind') is not True or not ann.get('guideline_version'):
        raise ValueError('Annotator identity, blind attestation and guideline version are required')
    if (ann.get('role') not in allowed_roles or ann.get('seniority') not in SENIORITY or
            not isinstance(ann.get('ambiguous'), bool) or not isinstance(ann.get('multiple_roles'), bool)):
        raise ValueError('Annotation role, seniority or ambiguity flags are invalid')
    if ann['multiple_roles'] and ann['role'] != 'unknown':
        raise ValueError('Multiple independent positions require unknown')
    evidence = ann.get('evidence')
    if not isinstance(evidence, list):
        raise ValueError('Evidence must be a list')
    targets = set()
    for ev in evidence:
        if (not isinstance(ev, dict) or set(ev) != {'target', 'field', 'quote'} or
                ev['target'] not in ('primary_role', 'seniority') or ev['field'] not in ('title', 'description', 'requirements') or
                not isinstance(ev['quote'], str) or not ev['quote'] or ev['quote'] not in item[ev['field']]):
            raise ValueError('Annotation evidence does not match frozen input')
        targets.add(ev['target'])
    if (ann['role'] != 'unknown' and 'primary_role' not in targets) or (ann['seniority'] != 'unknown' and 'seniority' not in targets):
        raise ValueError('Annotation requires evidence for known role and seniority')
    return ann


def assemble_draft(corpus_id, left_path, right_path, output_path, preflight):
    jobs = frozen_pilot(corpus_id, preflight)
    expected = {job['jd_id']: job for job in jobs}
    def by_id(path):
        rows = _read_jsonl(path)
        mapping = {row['jd_id']: row for row in rows}
        if len(mapping) != len(rows) or set(mapping) != set(expected):
            raise ValueError('Each annotation file must contain exactly the pilot IDs')
        return mapping
    left, right = by_id(left_path), by_id(right_path)
    taxonomy = yaml.safe_load((ROOT / 'configs/role_taxonomy.yaml').read_text(encoding='utf-8'))
    allowed = {role for family in taxonomy.values() for role in family} | SPECIAL
    drafts, disagree, identities = [], 0, [set(), set()]
    for item in jobs:
        jd = item['jd_id']
        a = _validate_annotation(left[jd], item, allowed)
        b = _validate_annotation(right[jd], item, allowed)
        identities[0].add(a['annotator']); identities[1].add(b['annotator'])
        if a['annotator'] == b['annotator'] or a['guideline_version'] != b['guideline_version']:
            raise ValueError('Annotations must be independent and use the same guideline version')
        fields = ('role', 'seniority', 'ambiguous', 'multiple_roles')
        agree = all(a[field] == b[field] for field in fields)
        evidence = []
        if agree:
            for ev in a['evidence'] + b['evidence']:
                if ev not in evidence:
                    evidence.append(ev)
        else:
            disagree += 1
        # A human must explicitly sign off even matching labels; disagreements
        # remain unset until adjudicated. The draft cannot pass evaluate as gold.
        drafts.append({'jd_id': jd, **{field: a[field] if agree else None for field in fields},
                       'evidence': evidence, 'annotations': [a, b], 'agreement': agree,
                       'adjudicated': False, 'adjudicator': None})
    if any(len(group) != 1 for group in identities):
        raise ValueError('Each annotation file must have one consistent annotator')
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output, drafts)
    return {'sample_count': len(drafts), 'agreements': len(drafts) - disagree, 'disagreements': disagree,
            'draft': str(output), 'note': 'All rows require human adjudication before evaluation.'}
