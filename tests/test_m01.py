import json
from pathlib import Path

import pytest
from src.collection import runner


def test_validate_formats_and_missing(tmp_path):
    spec = {'format': 'json', 'title': 'title', 'description': 'desc'}
    path = tmp_path / 'jobs.json'
    path.write_text(json.dumps([{'title': 'Dev', 'desc': 'details'}, {'title': 'QA', 'desc': ''}]))
    assert runner.validate(path, spec)['missing_important_count'] == 1
    path.write_text('{bad')
    with pytest.raises(ValueError):
        runner.validate(path, spec)


def test_url_and_file_identity():
    assert runner.clean_url('https://EXAMPLE.com/job?id=2&utm_source=x#top') == 'https://example.com/job?id=2'
    assert runner.file_id('a/jobs.csv') != runner.file_id('b/jobs.csv')


def test_first_publish_then_skip_and_bad_data(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    source = {'source_id': 'test', 'repository': 'x/y', 'ref': 'main'}
    spec = {'path': 'jobs.json', 'format': 'json', 'title': 'title', 'description': 'desc'}
    version = ['a']
    monkeypatch.setattr(runner, 'revision', lambda *_: ('commit', version[0]))
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, _):
            if getattr(self, 'done', False): return b''
            self.done = True
            return b'[{"title":"Dev","desc":"Job"}]' if version[0] == 'a' else b'invalid'
    monkeypatch.setattr(runner, 'request', lambda _: Response())
    assert runner.ingest(source, spec, 'r1')['status'] == 'PUBLISHED'
    latest = tmp_path / 'data/raw/test/latest.json'
    before = latest.read_bytes()
    assert runner.ingest(source, spec, 'r2')['status'] == 'SKIPPED_UNCHANGED'
    version[0] = 'b'
    assert runner.ingest(source, spec, 'r3')['status'] == 'QUARANTINED'
    assert latest.read_bytes() == before


def test_issue_pages_publish_and_retain_latest_on_failure(tmp_path, monkeypatch):
    import io
    monkeypatch.setattr(runner, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    source = {'source_id': 'board', 'repository': 'org/repo', 'ref': 'main', 'type': 'github_issues'}
    spec = {'path': 'issues/open.jsonl', 'format': 'jsonl', 'title': 'title', 'description': 'body'}
    issue = {'number': 1, 'title': 'Developer', 'body': 'Build things', 'html_url': 'https://github.com/org/repo/issues/1'}
    class Response(io.BytesIO):
        def __init__(self, items, headers=None):
            super().__init__(json.dumps(items).encode())
            self.headers = headers or {}
    monkeypatch.setattr(runner, 'request', lambda url: Response([issue], {'Link': '<https://example.test/next>; rel="next"'}) if 'api.github' in url else Response([{'number': 2, 'title': 'PR', 'body': 'ignore', 'pull_request': {}}]))
    assert runner.ingest(source, spec, 'one')['status'] == 'PUBLISHED'
    latest = tmp_path / 'data/raw/board/latest.json'
    before = latest.read_bytes()
    def fail_second(url):
        if 'api.github' in url:
            return Response([issue], {'Link': '<https://example.test/next>; rel="next"'})
        raise OSError('network down')
    monkeypatch.setattr(runner, 'request', fail_second)
    assert runner.ingest(source, spec, 'two')['status'] == 'FAILED'
    assert latest.read_bytes() == before
