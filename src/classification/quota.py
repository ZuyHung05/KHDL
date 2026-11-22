"""Conservative local quota reservations, shared by runs of one project."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


class QuotaPaused(Exception):
    pass


class RateWait(Exception):
    def __init__(self, seconds):
        self.seconds = max(0.01, seconds)
        super().__init__('Local minute quota requires waiting')


def validate_limits(config):
    names = ('rpm', 'input_tpm', 'rpd', 'max_requests_per_run', 'max_input_tokens_per_run')
    for name in names:
        value = config.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError('Positive integer quota is required: ' + name)
    for name in ('max_requests_per_minute', 'max_requests_per_day'):
        if name in config and (isinstance(config[name], bool) or not isinstance(config[name], int) or config[name] <= 0):
            raise ValueError('Positive integer limit is required: ' + name)
    if not config.get('project_id'):
        raise ValueError('A stable project_id is required for shared quota accounting')
    return config


def reserve(state, run_id, config, tokens, now=None, kind='generate'):
    validate_limits(config)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Time must be timezone-aware')
    now = now.astimezone(timezone.utc)
    stamp = now.isoformat(timespec='microseconds')
    day = now.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
    cutoff = (now - timedelta(seconds=60)).isoformat(timespec='microseconds')
    project = config['project_id']
    def limit(key):
        amount = max(1, int(config[key] * 0.8))
        override = {'rpm': 'max_requests_per_minute', 'rpd': 'max_requests_per_day'}.get(key)
        return min(amount, config.get(override, amount))
    if kind not in ('generate', 'model_metadata') or tokens < 0 or (kind == 'generate' and tokens == 0) or tokens > limit('input_tpm'):
        raise QuotaPaused('Input reservation exceeds the configured per-minute budget')
    db = state.db
    with db:
        daily = db.execute('SELECT COUNT(*) FROM quota_requests WHERE project=? AND pacific_date=?', (project, day)).fetchone()[0]
        run_count, run_tokens = db.execute('SELECT COUNT(*), COALESCE(SUM(MAX(reserved_input_tokens, COALESCE(actual_input_tokens, 0))),0) FROM quota_requests WHERE run_id=?', (run_id,)).fetchone()
        if daily >= limit('rpd'):
            raise QuotaPaused('Daily project request quota reached')
        if run_count >= config['max_requests_per_run'] or run_tokens + tokens > config['max_input_tokens_per_run']:
            raise QuotaPaused('Configured run budget reached')
        recent = db.execute('SELECT started_at, MAX(reserved_input_tokens, COALESCE(actual_input_tokens,0)) FROM quota_requests WHERE project=? AND started_at>? ORDER BY started_at', (project, cutoff)).fetchall()
        if len(recent) >= limit('rpm') or sum(row[1] for row in recent) + tokens > limit('input_tpm'):
            oldest = datetime.fromisoformat(recent[0][0])
            raise RateWait((oldest + timedelta(seconds=60) - now).total_seconds() + 0.01)
        cur = db.execute('INSERT INTO quota_requests(project,run_id,started_at,pacific_date,reserved_input_tokens,kind) VALUES (?,?,?,?,?,?)', (project, run_id, stamp, day, tokens, kind))
        return cur.lastrowid


def record_usage(state, reservation_id, actual_input_tokens):
    if actual_input_tokens is not None:
        with state.db:
            state.db.execute('UPDATE quota_requests SET actual_input_tokens=? WHERE id=?', (actual_input_tokens, reservation_id))
