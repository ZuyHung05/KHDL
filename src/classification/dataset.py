"""Reconstruct and freeze the existing M01 corpus without changing raw data."""
import hashlib
import json
import re
import unicodedata
import html
import random
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import yaml
from src.collection import runner
from .rules import classify

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/curated/role_classification/corpora'


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def requirements(sid, row):
    key = {'vietjobs': 'requirements_text', 'careersgovsg': 'jobRequirements',
           'ady201m': 'Yêu cầu ứng viên'}.get(sid)
    return str(row.get(key) or '') if key else ''


def api_description(sid, row, desc):
    if sid == 'careersgovsg':
        responsibilities = str(row.get('jobResponsibilities') or '').strip()
        return '\n\n'.join(part for part in (desc, responsibilities) if part)
    return desc


def build_corpus():
    taxonomy_path = ROOT / 'configs/role_taxonomy.yaml'
    taxonomy = yaml.safe_load(taxonomy_path.read_text(encoding='utf-8'))
    unique, url_groups, snapshots = {}, {}, []
    for source in runner.registry():
        sid = source['source_id']
        root = ROOT / 'data/raw' / sid
        latest = runner.read_json(root / 'latest.json', {'files': {}})
        specs = {x['path']: x for x in source['files']}
        for entry in latest['files'].values():
            spec = specs.get(entry['source_file'])
            if not spec:
                continue
            path = root / entry['snapshot'] / Path(entry['source_file']).name
            if runner.sha256_file(path) != entry['file_sha256']:
                raise ValueError('Snapshot checksum mismatch: ' + str(path))
            snapshots.append({'source_id': sid, **entry, 'mapping': spec})
            for index, row in enumerate(runner.rows(path, spec)):
                title = str(row.get(spec['title']) or '').strip()
                desc = str(row.get(spec['description']) or '').strip()
                company = str(row.get(spec.get('company', '')) or '').strip()
                url = runner.clean_url(str(row.get(spec.get('url', '')) or ''))
                content = digest('\0'.join(map(runner.normalized, (title, company, desc))))
                key = 'content:' + content
                if url:
                    compatible = next((k for k in url_groups.get(url, []) if runner.normalized(unique[k]['title']) == runner.normalized(title) and (not company or not unique[k]['company'] or runner.normalized(unique[k]['company']) == runner.normalized(company))), None)
                    key = compatible or ('url:' + url + ':' + content)
                    url_groups.setdefault(url, []).append(key)
                member = {'source_id': sid, 'file': entry['source_file'], 'snapshot': entry['snapshot'], 'sha256': entry['file_sha256'], 'row_index': index, 'issue_number': row.get('number')}
                if key not in unique:
                    unique[key] = {'jd_id': digest(key), 'title': title, 'description': desc, 'api_description': api_description(sid, row, desc), 'requirements': requirements(sid, row), 'company': company, 'url': url, 'source_members': []}
                unique[key]['source_members'].append(member)
                if len(desc) > len(unique[key]['description']):
                    unique[key].update(title=title, description=desc, api_description=api_description(sid, row, desc), company=company, requirements=requirements(sid, row))
    for record in unique.values():
        status, family, role = classify(record['title'], taxonomy)
        record.update(rule_status=status, rule_family=family, rule_primary_role=role,
                      preprocessing_version='nfc_redact_v6')
        record['content_hash'] = content_hash(payload(record))
    return list(unique.values()), snapshots, runner.sha256_file(taxonomy_path)


def prepare(corpus_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', corpus_id):
        raise ValueError('Invalid corpus ID')
    records, snapshots, taxonomy_hash = build_corpus()
    if not snapshots:
        raise ValueError('No published snapshots')
    dest = OUT / corpus_id
    OUT.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError('Corpus already exists: ' + corpus_id)
    staging = Path(tempfile.mkdtemp(prefix='.prepare-', dir=OUT))
    try:
        candidates = [x for x in records if x['rule_status'] in ('unknown', 'needs_review')]
        for name, selected in [('corpus.jsonl', records), ('candidates.jsonl', candidates)]:
            with (staging / name).open('w', encoding='utf-8') as f:
                for item in selected:
                    f.write(json.dumps(item, ensure_ascii=False) + '\n')
        samples = sample_candidates(candidates)
        runner.write_json(staging / 'samples.json', samples)
        counts = {x: sum(r['rule_status'] == x for r in records) for x in ('classified', 'unknown', 'needs_review')}
        manifest = {'corpus_id': corpus_id, 'created_at': runner.now(), 'snapshots': snapshots, 'taxonomy_sha256': taxonomy_hash, 'dedup_version': 'm01_v1', 'rule_version': 'title_alias_v1', 'preprocessing_version': 'nfc_redact_v6', 'counts': counts, 'total': len(records), 'artifacts_sha256': {name: runner.sha256_file(staging / name) for name in ('corpus.jsonl', 'candidates.jsonl', 'samples.json')}}
        runner.write_json(staging / 'corpus_manifest.json', manifest)
        staging.rename(dest)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return manifest


def sanitize(text, version='nfc_redact_v2'):
    if version not in ('nfc_redact_v2', 'nfc_redact_v3', 'nfc_redact_v4', 'nfc_redact_v5', 'nfc_redact_v6'):
        raise ValueError('Unknown preprocessing version')
    text = unicodedata.normalize('NFC', html.unescape((text or '').replace('\r\n', '\n').replace('\r', '\n')))
    if version in ('nfc_redact_v3', 'nfc_redact_v4', 'nfc_redact_v5', 'nfc_redact_v6'):
        text = re.sub(r'\[([^\]\n]+)\]\((?:https?://|mailto:)[^)]+\)', r'\1', text, flags=re.I)
        text = text.replace('**', '').replace('__', '')
    text = re.sub(r'(?i)<\s*br\s*/?\s*>|</\s*(?:p|div|li|h[1-6])\s*>', '\n', text)
    if version in ('nfc_redact_v5', 'nfc_redact_v6'):
        text = re.sub(r'(?i)</?(?:p|div|span|b|strong|em|i|ul|ol|li|h[1-6]|table|tr|td|th|a|section)\b[^>]*>', '', text)
        # Match headings, not title/prose prefixes such as "Application Engineer".
        text = re.sub(r'(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:contact(?: information| details)?|apply(?: now)?|application(?: process| instructions)?|liên hệ|ứng tuyển)[ \t]*(?:[:：][^\n]*|[ \t]*)$(?:.*?)(?=\n[ \t]*#|\Z)', '[contact removed]', text, flags=re.S)
    else:
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'(?im)^\s*(?:#{1,6}\s*)?(?:contact|apply|application|liên hệ|ứng tuyển)\s*:?.*?(?=\n\s*#|\Z)', '[contact removed]', text, flags=re.S)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email removed]', text)
    text = re.sub(r'(?<!\w)(?:\+?\d[\d .()-]{7,}\d)(?!\w)', '[phone removed]', text)
    text = re.sub(r'(?i)\b(?:https?://|www\.)\S+', '[link removed]', text)
    text = re.sub(r'(?im)^.*\b(?:telegram|zalo|skype|whatsapp|wechat)\s*[:：].*$', '[contact removed]', text)
    text = re.sub(r'(?im)^.*\b(?:telegram|zalo|skype|whatsapp|wechat)\b[^\n]*(?:\[phone removed\]|\[email removed\]).*$', '[contact removed]', text)
    if version == 'nfc_redact_v6':
        text = re.sub(r'(?im)^.*\b(?:telegram|zalo|skype|whatsapp|wechat)\b[^\n]*(?:@[\w.\-]+|\b(?:id|username|user name|account)\s*[:：=]\s*\S+).*$', '[contact removed]', text)
    if version in ('nfc_redact_v4', 'nfc_redact_v5', 'nfc_redact_v6'):
        text = re.sub(r'(?m)^\s*#{1,6}\s+', '', text)
    return text


def payload(record):
    version = record.get('preprocessing_version', 'nfc_redact_v2')
    return {'jd_id': record['jd_id'], 'title': sanitize(record.get('title', ''), version),
            'description': sanitize(record.get('api_description', record.get('description', '')), version),
            'requirements': sanitize(record.get('requirements', ''), version)}


def content_hash(item):
    fields = {key: item[key] for key in ('title', 'description', 'requirements')}
    return digest(json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def sample_candidates(candidates, seed=42):
    """Sample input-hash groups without overlap; each stratum records its group inclusion rate."""
    groups = {}
    for record in candidates:
        groups.setdefault(record['content_hash'], []).append(record)
    strata = defaultdict(list)
    for key, records in groups.items():
        representative = records[0]
        source = representative['source_members'][0]['source_id']
        strata[(source, representative['rule_status'])].append((key, representative['jd_id']))
    rng = random.Random(seed)
    for items in strata.values():
        rng.shuffle(items)
    results = {}
    for stage, requested in [('smoke50', 50), ('pilot200', 200)]:
        remaining = sum(map(len, strata.values()))
        if remaining < requested:
            raise ValueError('Not enough independent input groups for sampling')
        # Cover every non-empty stratum when the sample size permits, then
        # distribute remaining slots proportionally to remaining capacity.
        nonempty = [k for k, values in strata.items() if values]
        minimum = 1 if requested >= len(nonempty) else 0
        alloc = {k: minimum if k in nonempty else 0 for k in strata}
        slots = requested - sum(alloc.values())
        capacities = {k: len(values) - alloc[k] for k, values in strata.items()}
        capacity_total = sum(capacities.values())
        if slots:
            for k in strata:
                alloc[k] += slots * capacities[k] // capacity_total
            order = sorted(strata, key=lambda k: (-(slots * capacities[k] % capacity_total), k))
            for k in order[:requested - sum(alloc.values())]:
                alloc[k] += 1
        selected = []
        for key in sorted(strata):
            pool = strata[key]
            count, population = alloc[key], len(pool)
            selected.extend({'jd_id': jd, 'content_hash': h, 'source_id': key[0], 'rule_status': key[1],
                             'group_inclusion_probability': count / population} for h, jd in pool[:count])
            del pool[:count]
        results[stage] = selected
    return {'seed': seed, 'sampling_unit': 'unique normalized input hash', 'stages': results}


def audit_samples(candidates, samples):
    """Validate disjoint sampled hash groups and expose uncovered pilot strata.

    Pilot probabilities are conditional on the smoke groups already removed; the
    population is unique input hashes, not individual raw rows or JD IDs.
    """
    groups = {}
    for record in candidates:
        groups.setdefault(record['content_hash'], record)
    stages = samples['stages']
    smoke, pilot = stages['smoke50'], stages['pilot200']
    if len(smoke) != 50 or len(pilot) != 200:
        raise ValueError('Unexpected smoke or pilot sample size')
    for stage in (smoke, pilot):
        hashes = [item['content_hash'] for item in stage]
        if len(set(hashes)) != len(hashes):
            raise ValueError('Duplicate input hash within a sample')
        for item in stage:
            representative = groups.get(item['content_hash'])
            if (not representative or item['jd_id'] != representative['jd_id'] or
                    item['source_id'] != representative['source_members'][0]['source_id'] or
                    item['rule_status'] != representative['rule_status']):
                raise ValueError('Sample does not match its representative candidate')
    smoke_hashes = {item['content_hash'] for item in smoke}
    if smoke_hashes.intersection(item['content_hash'] for item in pilot):
        raise ValueError('Smoke and pilot input hashes overlap')
    initial_population = defaultdict(int)
    smoke_selected = defaultdict(int)
    for representative in groups.values():
        initial_population[(representative['source_members'][0]['source_id'], representative['rule_status'])] += 1
    for item in smoke:
        smoke_selected[(item['source_id'], item['rule_status'])] += 1
    for item in smoke:
        key = (item['source_id'], item['rule_status'])
        probability = item.get('group_inclusion_probability')
        if not isinstance(probability, (int, float)) or abs(probability - smoke_selected[key] / initial_population[key]) > 1e-12:
            raise ValueError('Smoke inclusion probability does not match sample design')
    population = defaultdict(int)
    for digest_value, representative in groups.items():
        if digest_value not in smoke_hashes:
            population[(representative['source_members'][0]['source_id'], representative['rule_status'])] += 1
    selected = defaultdict(int)
    for item in pilot:
        selected[(item['source_id'], item['rule_status'])] += 1
    rows = []
    for (source, status), total in sorted(population.items()):
        count = selected[(source, status)]
        probability = count / total
        rows.append({'source_id': source, 'rule_status': status, 'eligible_groups': total,
                     'pilot_groups': count, 'conditional_inclusion_probability': probability})
    for item in pilot:
        key = (item['source_id'], item['rule_status'])
        probability = item.get('group_inclusion_probability')
        if not isinstance(probability, (int, float)) or abs(probability - selected[key] / population[key]) > 1e-12:
            raise ValueError('Pilot inclusion probability does not match sample design')
    uncovered = [row for row in rows if row['pilot_groups'] == 0]
    return {'sampling_unit': 'unique normalized input hash', 'probability_scope': 'conditional on smoke sample removed',
            'candidate_records': len(candidates), 'candidate_input_groups': len(groups),
            'eligible_groups_after_smoke': sum(population.values()), 'pilot_sample_groups': len(pilot),
            'strata': rows, 'unrepresented_strata': uncovered,
            'unrepresented_groups': sum(row['eligible_groups'] for row in uncovered),
            'interpretation': 'Pilot metrics are unweighted sample metrics, not estimates for all JD records.'}
