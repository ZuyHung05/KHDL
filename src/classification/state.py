"""Durable local state for classification. Raw API payloads never enter event logs."""
import contextlib
import fcntl
import hashlib
import json
import sqlite3
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def cache_key(parts):
    return hashlib.sha256(canonical(parts).encode('utf-8')).hexdigest()


@contextlib.contextmanager
def project_lock(path):
    """Serialize workers sharing project quota; flock releases automatically on crash."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another classification process holds the project lock') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class State:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, manifest TEXT NOT NULL, status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            run_id TEXT NOT NULL REFERENCES runs(run_id), jd_id TEXT NOT NULL,
            status TEXT NOT NULL, cache_key TEXT NOT NULL, result TEXT,
            cache_hit INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (run_id, jd_id)
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, jd_id TEXT NOT NULL,
            started_at TEXT NOT NULL, status TEXT NOT NULL, error_code TEXT,
            latency_ms INTEGER, usage TEXT
        );
        CREATE TABLE IF NOT EXISTS cache (
            cache_key TEXT PRIMARY KEY, result TEXT NOT NULL, model_version TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quota_requests (
            id INTEGER PRIMARY KEY, project TEXT NOT NULL, run_id TEXT NOT NULL,
            started_at TEXT NOT NULL, pacific_date TEXT NOT NULL, reserved_input_tokens INTEGER NOT NULL,
            actual_input_tokens INTEGER
        );
        CREATE INDEX IF NOT EXISTS quota_project_time ON quota_requests(project, started_at);
        ''')
        if 'kind' not in {row[1] for row in self.db.execute('PRAGMA table_info(quota_requests)')}:
            self.db.execute("ALTER TABLE quota_requests ADD COLUMN kind TEXT NOT NULL DEFAULT 'generate'")
        self.db.commit()

    def close(self):
        self.db.close()

    def create_run(self, run_id, manifest, tasks):
        with self.db:
            self.db.execute('INSERT INTO runs VALUES (?, ?, ?)', (run_id, canonical(manifest), 'PENDING'))
            self.db.executemany('INSERT INTO tasks(run_id,jd_id,status,cache_key) VALUES (?,?,?,?)',
                                [(run_id, jd, 'PENDING', key) for jd, key in tasks])

    def recover(self, run_id):
        with self.db:
            self.db.execute("UPDATE tasks SET status='PENDING' WHERE run_id=? AND status IN ('RUNNING','RETRY_WAIT','FAILED')", (run_id,))
            self.db.execute("UPDATE attempts SET status='UNKNOWN_INTERRUPTED' WHERE run_id=? AND status='RUNNING'", (run_id,))

    def claim(self, run_id, jd_id):
        with self.db:
            cur = self.db.execute("UPDATE tasks SET status='RUNNING', attempts=attempts+1 WHERE run_id=? AND jd_id=? AND status='PENDING'", (run_id, jd_id))
            return cur.rowcount == 1

    def cached(self, key):
        row = self.db.execute('SELECT result, model_version FROM cache WHERE cache_key=?', (key,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def begin_attempt(self, run_id, jd_id, started_at):
        with self.db:
            cur = self.db.execute("INSERT INTO attempts(run_id,jd_id,started_at,status) VALUES (?,?,?,'RUNNING')", (run_id, jd_id, started_at))
            return cur.lastrowid

    def end_attempt(self, attempt_id, status, error_code=None, latency_ms=None, usage=None):
        with self.db:
            self.db.execute('UPDATE attempts SET status=?, error_code=?, latency_ms=?, usage=? WHERE id=?',
                            (status, error_code, latency_ms, canonical(usage) if usage is not None else None, attempt_id))

    def finish(self, run_id, jd_id, key, result, model_version, cache_hit=False,
               attempt_id=None, latency_ms=None, usage=None, cache_result=None):
        status = 'REVIEW_REQUIRED' if result['review_required'] else 'PROPOSED'
        # The cache stores content-derived evidence, not an ID belonging to a different job.
        cache_result = {**(cache_result if cache_result is not None else result), 'jd_id': ''}
        with self.db:
            if not cache_hit:
                self.db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (key, canonical(cache_result), model_version))
            cur = self.db.execute("UPDATE tasks SET status=?, result=?, cache_hit=? WHERE run_id=? AND jd_id=? AND status='RUNNING'", (status, canonical(result), int(cache_hit), run_id, jd_id))
            if cur.rowcount != 1:
                raise RuntimeError('Task was not claimed')
            if attempt_id is not None:
                self.db.execute("UPDATE attempts SET status='VALID', latency_ms=?, usage=? WHERE id=?", (latency_ms, canonical(usage), attempt_id))

    def set_task(self, run_id, jd_id, status, result=None):
        if status not in {'PENDING', 'REVIEW_REQUIRED', 'FAILED', 'RETRY_WAIT'}:
            raise ValueError('Invalid task status')
        with self.db:
            self.db.execute('UPDATE tasks SET status=?, result=? WHERE run_id=? AND jd_id=?',
                            (status, canonical(result) if result is not None else None, run_id, jd_id))
