import pytest
from pathlib import Path
import pytest
from src.classification.dataset import build_corpus, sanitize
from src.classification.validation import validate


@pytest.mark.skipif(not (Path(__file__).resolve().parents[2]/'data/reports/ingestion_summary.json').exists(), reason='Local real-data regression; datasets are intentionally not committed')
def test_corpus_reproduces_current_report():
    from src.collection.runner import ROOT, read_json
    report = read_json(ROOT / 'data/reports/ingestion_summary.json', {})
    corpus, _, _ = build_corpus()
    assert len(corpus) == report['unique_jd']
    for status in ('unknown', 'needs_review'):
        assert sum(x['rule_status'] == status for x in corpus) == report[status]
    assert len({x['jd_id'] for x in corpus}) == len(corpus)


def test_contact_redaction():
    assert 'test@example.com' not in sanitize('Email test@example.com')
    assert '0912345678' not in sanitize('Phone 0912345678')


def test_evidence_and_taxonomy():
    item = {'jd_id': '1', 'title': 'Senior Cloud Engineer', 'description': 'Build landing zones', 'requirements': ''}
    result = {'jd_id': '1', 'primary_role': 'Cloud', 'role_family': 'Infrastructure & Security', 'seniority': 'senior', 'evidence': [{'target': 'primary_role', 'field': 'description', 'quote': 'landing zones'}, {'target': 'seniority', 'field': 'title', 'quote': 'Senior'}], 'review_required': False, 'review_reasons': []}
    assert validate(result, item) == result
    result['evidence'][0]['quote'] = 'invented'
    with pytest.raises(ValueError): validate(result, item)


def test_preflight_detects_changed_candidates(tmp_path, monkeypatch):
    import hashlib
    import json
    from src.classification import runner as cli
    root = tmp_path
    corpus = root / 'corpora' / 'test'
    corpus.mkdir(parents=True)
    taxonomy = root / 'configs' / 'role_taxonomy.yaml'
    taxonomy.parent.mkdir()
    taxonomy.write_text('test', encoding='utf-8')
    raw = root / 'data/raw/source/snapshot/file.json'
    raw.parent.mkdir(parents=True)
    raw.write_text('raw', encoding='utf-8')
    sha = lambda value: hashlib.sha256(value.encode()).hexdigest()
    item = {'jd_id': 'one', 'rule_status': 'unknown', 'source_members': [{}]}
    manifest = {'corpus_id': 'test', 'total': 1, 'counts': {'classified': 0, 'unknown': 1, 'needs_review': 0},
                'taxonomy_sha256': sha('test'), 'snapshots': [{'source_id': 'source', 'snapshot': 'snapshot', 'source_file': 'file.json', 'file_sha256': sha('raw')}]}
    (corpus / 'corpus_manifest.json').write_text(json.dumps(manifest))
    (corpus / 'corpus.jsonl').write_text(json.dumps(item) + '\n')
    (corpus / 'candidates.jsonl').write_text(json.dumps(item) + '\n')
    monkeypatch.setattr(cli, 'OUT', root / 'corpora')
    monkeypatch.setattr(cli, 'ROOT', root)
    assert cli.preflight('test')['candidates'] == 1
    manifest['artifacts_sha256'] = {'corpus.jsonl': sha((corpus / 'corpus.jsonl').read_text())}
    (corpus / 'corpus_manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='hash list is incomplete'):
        cli.preflight('test')
    del manifest['artifacts_sha256']
    (corpus / 'corpus_manifest.json').write_text(json.dumps(manifest))
    (corpus / 'candidates.jsonl').write_text('')
    with pytest.raises(ValueError, match='inconsistent'):
        cli.preflight('test')
    raw.write_text('modified')
    with pytest.raises(ValueError, match='checksum'):
        cli.preflight('test')
