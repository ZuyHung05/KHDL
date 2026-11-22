"""Validate model proposals against source evidence and the existing taxonomy."""
import yaml
from .dataset import ROOT
from .schema import Proposal

SENIORITY = {'intern', 'junior', 'mid', 'senior', 'lead', 'manager', 'unknown'}
SPECIAL = {'other_it_role', 'non_it', 'unknown'}


def validate(result, item):
    result = Proposal.model_validate(result).model_dump()
    fields = {'jd_id', 'primary_role', 'role_family', 'seniority', 'evidence', 'review_required', 'review_reasons'}
    if not isinstance(result, dict) or set(result) != fields or result['jd_id'] != item['jd_id']:
        raise ValueError('Invalid response fields or JD ID')
    taxonomy = yaml.safe_load((ROOT / 'configs/role_taxonomy.yaml').read_text(encoding='utf-8'))
    roles = {role: family for family, items in taxonomy.items() for role in items}
    role = result['primary_role']
    if role not in roles and role not in SPECIAL:
        raise ValueError('Invalid role')
    if result['role_family'] != roles.get(role):
        raise ValueError('Role and family do not match')
    if result['seniority'] not in SENIORITY or not isinstance(result['review_required'], bool) or not isinstance(result['review_reasons'], list) or not isinstance(result['evidence'], list):
        raise ValueError('Invalid response types')
    targets = set()
    for ev in result['evidence']:
        if not isinstance(ev, dict) or set(ev) != {'target', 'field', 'quote'} or ev['target'] not in ('primary_role', 'seniority') or ev['field'] not in ('title', 'description', 'requirements') or not isinstance(ev['quote'], str) or not ev['quote'] or ev['quote'] not in item.get(ev['field'], ''):
            raise ValueError('Invalid evidence')
        targets.add(ev['target'])
    if role != 'unknown' and 'primary_role' not in targets:
        raise ValueError('Missing role evidence')
    if result['seniority'] != 'unknown' and 'seniority' not in targets:
        raise ValueError('Missing seniority evidence')
    if role == 'unknown' and not result['review_required']:
        raise ValueError('Unknown requires review')
    return result


def evidence_offsets(result, item):
    """Offsets are zero-based Unicode character indices in the submitted fields."""
    offsets = []
    for evidence in result['evidence']:
        start = item[evidence['field']].index(evidence['quote'])
        offsets.append({**evidence, 'start': start, 'end': start + len(evidence['quote'])})
    return offsets
