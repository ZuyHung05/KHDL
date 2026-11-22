"""Sequential, checkpointed classification execution with no raw content in logs."""
from datetime import datetime, timezone
import json
import re
import random
import time

from .dataset import ROOT, content_hash
from .gemini_client import usage_dict
from .quota import reserve, record_usage, QuotaPaused, RateWait
from .schema import Proposal
from .validation import validate


class StopRun(Exception):
    pass


def has_job_text(item):
    text = ' '.join(item.get(k, '') for k in ('description', 'requirements'))
    text = re.sub(r'\[(?:contact|phone|email|link) removed\]', '', text, flags=re.I)
    return bool(text.strip())


def estimate_tokens(item):
    # Deliberately conservative reservation, not a provider token count. Unknown or
    # failed requests retain the reservation. Actual provider counts are recorded.
    prompt = (ROOT / 'prompts/role_classification_v1.txt').read_text(encoding='utf-8')
    defs = (ROOT / 'configs/role_definitions.yaml').read_text(encoding='utf-8')
    schema = json.dumps(Proposal.model_json_schema(), ensure_ascii=False)
    return len((prompt + defs + schema + json.dumps(item, ensure_ascii=False)).encode('utf-8')) + 1024


def classify_one(state, run_id, item, key, client, quota, actual_model_version,
                 max_input_characters=60000, sleep=time.sleep, cloud_requires_review=True,
                 expected_model_version=None):
    """Return the observed model version; errors stored without provider exception text."""
    jd_id = item['jd_id']
    if not state.claim(run_id, jd_id):
        return actual_model_version
    text = '\n'.join(item.get(k, '') for k in ('title', 'description', 'requirements'))
    if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\w)\+?\d[\d .()-]{7,}\d(?!\w)|\b(?:https?://|www\.)\S+|(?i:\b(?:zalo|telegram|whatsapp|skype|wechat)\s*[:=]\s*\S+)', text):
        state.set_task(run_id, jd_id, 'REVIEW_REQUIRED', {'reason': 'redaction_check_failed'})
        return actual_model_version
    if not has_job_text(item):
        state.set_task(run_id, jd_id, 'REVIEW_REQUIRED', {'reason': 'insufficient_text'})
        return actual_model_version
    if re.search(r'(?i)\b(?:nhiều vị trí|multiple (?:positions|roles|vacancies)|several (?:positions|roles|vacancies))\b', item['title'] + '\n' + item['description']):
        state.set_task(run_id, jd_id, 'REVIEW_REQUIRED', {'reason': 'multiple_positions'})
        return actual_model_version
    if sum(len(item[k]) for k in ('title', 'description', 'requirements')) > max_input_characters:
        state.set_task(run_id, jd_id, 'REVIEW_REQUIRED', {'reason': 'input_too_long'})
        return actual_model_version
    cached = state.cached(key)
    if cached and actual_model_version and cached[1] == actual_model_version:
        result = {**cached[0], 'jd_id': jd_id}
        try:
            validate(result, item)
        except ValueError:
            cached = None
        else:
            if cloud_requires_review and result['primary_role'] == 'Cloud':
                result['review_required'] = True
                result['review_reasons'] = list(dict.fromkeys(result['review_reasons'] + ['cloud_insufficient_gold']))[:8]
            state.finish(run_id, jd_id, key, result, actual_model_version, cache_hit=True)
            return actual_model_version
    # Retry limits are per task, not per Python process: quota pauses and crashes
    # must not silently grant another schema correction or network retry budget.
    previous = state.db.execute(
        'SELECT status,error_code FROM attempts WHERE run_id=? AND jd_id=? ORDER BY id',
        (run_id, jd_id)).fetchall()
    invalid_responses = sum(status == 'INVALID_RESPONSE' for status, _ in previous)
    transport_attempts = sum(
        status == 'UNKNOWN_INTERRUPTED' or
        (status == 'ERROR' and (code == 'CONNECTION_ERROR' or
                                bool(code and code.isdigit() and int(code) >= 500)))
        for status, code in previous)
    if invalid_responses >= 1:
        state.set_task(run_id, jd_id, 'REVIEW_REQUIRED', {'reason': 'invalid_response_or_evidence'})
        return actual_model_version
    if transport_attempts >= 3:
        state.set_task(run_id, jd_id, 'FAILED', {'reason': 'provider_error', 'code': 'RETRY_LIMIT'})
        return actual_model_version
    if estimate_tokens(item) > int(quota['input_tpm'] * 0.8):
        state.set_task(run_id, jd_id, 'REVIEW_REQUIRED', {'reason': 'input_exceeds_token_budget'})
        return actual_model_version
    while True:
        try:
            while True:
                try:
                    reservation = reserve(state, run_id, quota, estimate_tokens(item))
                    break
                except RateWait as exc:
                    sleep(exc.seconds)
        except QuotaPaused:
            state.set_task(run_id, jd_id, 'PENDING')
            raise
        attempt = state.begin_attempt(run_id, jd_id, datetime.now(timezone.utc).isoformat())
        start = time.monotonic()
        try:
            response = client.generate(item, correction=invalid_responses > 0)
        except Exception as exc:
            latency = int((time.monotonic() - start) * 1000)
            code = getattr(exc, 'code', None)
            if not isinstance(code, int):
                code = 'CONNECTION_ERROR'
            diagnostic = str(code)
            if code == 400:
                # Extract only controlled categories; never persist the provider message.
                message = str(getattr(exc, 'message', '')).lower()
                flags = [name for name, terms in {
                    'schema': ('schema', 'json'), 'model': ('model',),
                    'unsupported': ('unsupported', 'not supported'),
                    'invalid_argument': ('invalid argument', 'invalid_argument'),
                    'location': ('location', 'region', 'country'),
                    'billing': ('billing', 'free tier', 'quota'),
                    'api_key': ('api key', 'api_key'),
                }.items() if any(term in message for term in terms)]
                if flags:
                    diagnostic += ':' + ','.join(flags)
            state.end_attempt(attempt, 'ERROR', diagnostic, latency, {'unknown_usage': True})
            transport_attempts += 1
            # A 429 always stops as explicitly requested, regardless of retry metadata.
            if code == 429:
                state.set_task(run_id, jd_id, 'PENDING')
                raise QuotaPaused('Provider returned 429') from None
            if isinstance(code, int) and code in (400, 401, 403, 404):
                state.set_task(run_id, jd_id, 'PENDING')
                raise StopRun('Provider rejected model, configuration or credentials (HTTP %d)' % code) from None
            if (code == 'CONNECTION_ERROR' or isinstance(code, int) and code >= 500) and transport_attempts < 3:
                sleep(min(2 ** transport_attempts, 8) + random.uniform(0, 1))
                continue
            state.set_task(run_id, jd_id, 'FAILED', {'reason': 'provider_error', 'code': str(code)})
            return actual_model_version
        latency = int((time.monotonic() - start) * 1000)
        usage = usage_dict(response)
        record_usage(state, reservation, usage.get('prompt_token_count'))
        observed = getattr(response, 'model_version', None) or 'unreported'
        if (actual_model_version is not None and observed != actual_model_version) or (expected_model_version is not None and observed != expected_model_version):
            state.end_attempt(attempt, 'MODEL_CHANGED', 'MODEL_VERSION_CHANGED', latency, usage)
            state.set_task(run_id, jd_id, 'PENDING')
            raise StopRun('Provider model version changed; start a new run')
        actual_model_version = observed
        # Record the observed version before proceeding so a crash cannot silently
        # resume the run with a different provider revision.
        with state.db:
            row = state.db.execute('SELECT manifest FROM runs WHERE run_id=?', (run_id,)).fetchone()
            manifest = json.loads(row[0])
            previous = manifest.get('actual_model_version')
            if previous is not None and previous != observed:
                raise StopRun('Provider model version changed; start a new run')
            manifest['actual_model_version'] = observed
            state.db.execute('UPDATE runs SET manifest=? WHERE run_id=?', (json.dumps(manifest, ensure_ascii=False, sort_keys=True), run_id))
        feedback = getattr(response, 'prompt_feedback', None)
        block_reason = getattr(feedback, 'block_reason', None) if feedback else None
        candidates = getattr(response, 'candidates', None) or []
        finish_reason = str(getattr(candidates[0], 'finish_reason', '') or '') if candidates else ''
        if (block_reason and 'UNSPECIFIED' not in str(block_reason)) or any(reason in finish_reason.upper() for reason in ('SAFETY', 'RECITATION', 'BLOCKLIST', 'PROHIBITED')):
            state.end_attempt(attempt, 'REFUSAL', 'SAFETY_OR_REFUSAL', latency, usage)
            state.set_task(run_id, jd_id, 'REVIEW_REQUIRED', {'reason': 'safety_or_refusal'})
            return actual_model_version
        try:
            parsed = getattr(response, 'parsed', None)
            if isinstance(parsed, Proposal):
                result = parsed.model_dump()
            elif isinstance(parsed, dict):
                result = parsed
            else:
                result = json.loads(response.text)
            result = validate(result, item)
        except (ValueError, TypeError, AttributeError):
            invalid_responses += 1
            state.end_attempt(attempt, 'INVALID_RESPONSE', 'SCHEMA_OR_EVIDENCE', latency, usage)
            state.set_task(run_id, jd_id, 'REVIEW_REQUIRED', {'reason': 'invalid_response_or_evidence'})
            return actual_model_version
        # Cache the validated model output separately from the run-specific Cloud
        # review policy; sufficient later gold may legitimately lift that policy.
        model_result = {**result, 'review_reasons': list(result['review_reasons'])}
        if cloud_requires_review and result['primary_role'] == 'Cloud':
            result['review_required'] = True
            result['review_reasons'] = list(dict.fromkeys(result['review_reasons'] + ['cloud_insufficient_gold']))[:8]
        state.finish(run_id, jd_id, key, result, observed, attempt_id=attempt, latency_ms=latency, usage=usage,
                     cache_result=model_result)
        return actual_model_version
