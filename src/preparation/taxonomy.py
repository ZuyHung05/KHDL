"""Conservative, evidence-backed family, role and skill suggestions."""
from __future__ import annotations

import json
import re

from .role_report import PATTERNS

TITLE_MATCHERS = [(family, role, re.compile(pattern, re.I))
                  for family, roles in PATTERNS.items() for role, pattern in roles.items()
                  if role != 'Software khác']
GENERIC_SOFTWARE = re.compile(PATTERNS['Software Engineering']['Software khác'], re.I)

# Body matches require an occupational phrase. Generic activities and technology
# names ("testing", "security", "React") are not evidence of the job's role.
BODY_PATTERNS = {
    'Fullstack': r'full[ -]?stack (?:engineer|developer|development|applications?)',
    'Backend': r'back[ -]?end (?:engineer|developer|development|services?|systems?|apis?)',
    'Frontend': r'front[ -]?end (?:engineer|developer|development|applications?|interfaces?|ui)',
    'Mobile': r'mobile (?:app(?:lication)?s?|engineer|developer|development)',
    'Embedded': r'embedded (?:software|systems?|engineer|developer|development)',
    'UI/UX': r'ui[ /-]?ux (?:designer|design)|(?:product|ux|ui) designer',
    'Data Engineer': r'data engineer(?:ing)?|kỹ sư dữ liệu',
    'Data Scientist': r'data scientist|khoa học dữ liệu',
    'AI/ML Engineer': r'(?:ai|ml|machine learning) engineer|ai[ /-]?ml (?:engineer|developer)',
    'Data Analyst/BI': r'data analyst|bi analyst|business intelligence analyst|phân tích dữ liệu',
    'DevOps/SRE': r'devops engineer|site reliability engineer|\bsre\b',
    'Cloud': r'cloud (?:engineer|architect|specialist)',
    'Cybersecurity': r'(?:cybersecurity|security|appsec) (?:engineer|analyst|specialist)|chuyên viên an toàn thông tin',
    'System/Network/IT Support': r'it support|helpdesk|network engineer|system (?:engineer|administrator)',
    'QA/Testing': r'(?:qa|qc|test automation|software test) engineer|software tester|kiểm thử phần mềm',
    'Business Analyst': r'business analyst|phân tích nghiệp vụ|bridge system engineer',
    'ERP/SAP': r'(?:sap|erp) (?:consultant|developer|engineer)',
}
BODY_MATCHERS = {role: re.compile(pattern, re.I) for role, pattern in BODY_PATTERNS.items()}
SKILLS = re.compile(r'(?<![\w])(?:C\+\+|C#|\.NET|Node\.js|JavaScript|TypeScript|Python|Java|SQL|PostgreSQL|MySQL|MongoDB|Kubernetes|Docker|Terraform|AWS|Azure|GCP|React|Angular|Linux|Git|CI/CD|Spark|Hadoop|Kafka|HTML|CSS)(?![\w])', re.I)


def enrich(row: dict) -> dict:
    """Title anchors the role; explicit body phrases can resolve generic titles."""
    fields = {'title': row.get('title') or '', 'duties': row.get('duties') or '',
              'requirements': row.get('requirements') or ''}
    evidence = {}
    for family, role, regex in TITLE_MATCHERS:
        hits = []
        match = regex.search(fields['title'][:1000])
        if match:
            hits.append({'field': 'title', 'quote': match.group()})
        body_regex = BODY_MATCHERS[role]
        for field in ('duties', 'requirements'):
            match = body_regex.search(fields[field][:12000])
            if match:
                hits.append({'field': field, 'quote': match.group()})
        if hits:
            evidence[(family, role)] = hits

    title_roles = [key for key, hits in evidence.items() if any(h['field'] == 'title' for h in hits)]
    generic_software = bool(GENERIC_SOFTWARE.search(fields['title']))
    family = role = 'unknown'
    confidence, numeric, chosen = 'insufficient_evidence', 0.0, None
    if len(title_roles) == 1:
        chosen = title_roles[0]
        corroborated = any(h['field'] != 'title' for h in evidence[chosen])
        confidence, numeric = ('high_heuristic', .85) if corroborated else ('title_heuristic', .70)
    elif len(title_roles) > 1:
        families = {f for f, _ in title_roles}
        if len(families) == 1:
            family, confidence = next(iter(families)), 'ambiguous_role'
        else:
            confidence = 'ambiguous_family'
    else:
        body_roles = [key for key, hits in evidence.items() if any(h['field'] == 'duties' for h in hits)]
        if generic_software:
            family = 'Software Engineering'
            body_roles = [key for key in body_roles if key[0] == family]
        if len(body_roles) == 1:
            chosen = body_roles[0]
            confidence, numeric = 'body_only_heuristic', .50
        elif len(body_roles) > 1:
            families = {f for f, _ in body_roles}
            if len(families) == 1: family = next(iter(families))
            confidence = 'ambiguous_role' if len(families) == 1 else 'ambiguous_family'
        elif generic_software:
            confidence = 'generic_title_only'
    if chosen:
        family, role = chosen

    skills, seen = [], set()
    for field in ('requirements', 'duties'):
        for match in SKILLS.finditer(fields[field][:12000]):
            key = match.group().casefold()
            if key not in seen:
                seen.add(key)
                skills.append({'skill': match.group(), 'field': field})
    candidates = [{'family': f, 'role': r, 'evidence': hits} for (f, r), hits in evidence.items()]
    return {**row, 'role_family': family, 'primary_role': role,
            'role_confidence': confidence, 'role_confidence_score': numeric,
            'role_evidence': json.dumps(evidence.get(chosen, []), ensure_ascii=False),
            'role_candidates': json.dumps(candidates, ensure_ascii=False),
            'skills_evidence': json.dumps(skills, ensure_ascii=False),
            'skill_count': len(skills)}
