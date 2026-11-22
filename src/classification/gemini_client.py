"""Single-JD Gemini structured-output adapter; never logs provider messages or prompts."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
import yaml

from .dataset import ROOT
from .schema import Proposal


def provider_schema():
    """Supply the SDK-supported subset; strict Pydantic validation still runs locally."""
    schema = Proposal.model_json_schema()
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()
                    if k not in {'additionalProperties', 'minLength', 'maxLength', 'maxItems', 'minItems', 'title'}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    return clean(schema)


def load_client(model, timeout_seconds=60):
    # dotenv keeps already exported environment variables authoritative.
    load_dotenv(ROOT / '.env', override=False)
    if not os.getenv('GEMINI_API_KEY'):
        raise ValueError('GEMINI_API_KEY is not configured')
    return GeminiClient(model, timeout_seconds)


class GeminiClient:
    def __init__(self, model, timeout_seconds=60):
        self.model = model
        self.client = genai.Client(api_key=os.environ['GEMINI_API_KEY'],
                                   http_options=types.HttpOptions(timeout=timeout_seconds * 1000,
                                                                  retry_options=types.HttpRetryOptions(attempts=1)))

    def model_revision(self):
        model = self.client.models.get(model=self.model)
        # Some providers expose an alias rather than an immutable revision.
        return model.version or model.name or self.model

    def generate(self, item, correction=False):
        template = (ROOT / 'prompts/role_classification_v1.txt').read_text(encoding='utf-8')
        definitions = yaml.safe_load((ROOT / 'configs/role_definitions.yaml').read_text(encoding='utf-8'))
        prompt = template.format(definitions=json.dumps(definitions, ensure_ascii=False),
                                 job=json.dumps(item, ensure_ascii=False))
        if correction:
            prompt += '\nYour previous response did not pass validation. Return a schema-valid response with exact quotes from the provided fields; abstain if uncertain.'
        response = self.client.models.generate_content(
            model=self.model, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='application/json', response_schema=provider_schema(),
                                               temperature=0))
        return response


def usage_dict(response):
    usage = getattr(response, 'usage_metadata', None)
    if usage is None:
        return {'unknown_usage': True}
    keys = ('prompt_token_count', 'candidates_token_count', 'thoughts_token_count',
            'cached_content_token_count', 'total_token_count')
    values = {key: getattr(usage, key, None) for key in keys}
    return values | {'unknown_usage': any(values[key] is None for key in ('prompt_token_count', 'candidates_token_count', 'total_token_count'))}
