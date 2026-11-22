"""Coverage reports from frozen rules and independently revalidated suggestions."""
from collections import Counter
from datetime import datetime, timezone
import csv
import json
from pathlib import Path

import yaml

from .dataset import ROOT, OUT, payload
from .validation import validate


def coverage(records, tasks, cloud_supported=False):
    taxonomy = yaml.safe_load((ROOT / 'configs/role_taxonomy.yaml').read_text(encoding='utf-8'))
    roles = [role for family in taxonomy.values() for role in family]
    labels = roles + ['other_it_role', 'non_it', 'unknown', 'needs_review']
    before, after, transitions = Counter(), Counter(), Counter()
    for record in records:
        prior = record['rule_primary_role'] if record['rule_status'] == 'classified' else record['rule_status']
        new = prior
        task = tasks.get(record['jd_id'])
        if task and prior in ('unknown', 'needs_review') and task['status'] == 'PROPOSED':
            try:
                proposal = validate(task['suggested'], payload(record))
                if not proposal['review_required'] and (proposal['primary_role'] != 'Cloud' or cloud_supported):
                    new = proposal['primary_role']
            except (ValueError, TypeError):
                pass
        before[prior] += 1; after[new] += 1; transitions[(prior, new)] += 1
    return taxonomy, [{'label': label, 'count': before[label]} for label in labels], \
        [{'label': label, 'count': after[label]} for label in labels], transitions


def write_csv(path, fieldnames, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(rows)


def charts(taxonomy, after, output, run_id, timestamp, version):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    counts = {row['label']: row['count'] for row in after}
    families = list(taxonomy)
    values = [sum(counts[role] for role in taxonomy[family]) for family in families]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(families, values)
    ax.tick_params(axis='x', labelrotation=15)
    ax.set_ylabel('JD count'); ax.set_title('Suggested coverage by family')
    fig.text(.01, .01, f"n={sum(counts.values())} total | {run_id} | {version} | {timestamp} | unresolved and exceptions excluded", fontsize=7)
    fig.tight_layout(rect=(0, .04, 1, 1)); fig.savefig(output / 'role_family_distribution.png', dpi=200); plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    for ax, family in zip(axes.flat, families):
        labels = list(taxonomy[family]); nums = [counts[role] for role in labels]
        ax.barh(labels, nums); ax.set_title(family); ax.invert_yaxis()
        ax.set_xlim(0, max(max(nums, default=0) * 1.16, 1))
        for index, value in enumerate(nums): ax.text(value, index, ' ' + str(value), va='center', fontsize=8)
    fig.suptitle('Role distribution: baseline plus validated suggestions')
    fig.text(.01, .01, f"n={sum(counts.values())} total | {run_id} | {version} | {timestamp} | suggestions are not ground truth", fontsize=7)
    fig.tight_layout(rect=(0, .04, 1, .96)); fig.savefig(output / 'role_distribution_4panels.png', dpi=200); plt.close(fig)


def report_run(run_id, base, manifest, summary):
    corpus = OUT / manifest['corpus_id']
    def load(path):
        with path.open(encoding='utf-8') as handle: return [json.loads(line) for line in handle if line.strip()]
    records = load(corpus / 'corpus.jsonl')
    tasks = {x['jd_id']: x for x in load(base / 'predictions.jsonl')}
    evaluation_path = base / 'reports/evaluation.json'
    evaluation = json.loads(evaluation_path.read_text()) if evaluation_path.exists() else {}
    # Until the cloud evidence is sufficient, predictions must be reviewed.
    cloud_supported = (manifest.get('stage') == 'full' and not manifest.get('cloud_requires_review', True)) or (bool(evaluation.get('full_gate')) and not evaluation.get('cloud_requires_review', True))
    taxonomy, before, after, transitions = coverage(records, tasks, cloud_supported)
    report_dir = base / 'reports'; report_dir.mkdir(parents=True, exist_ok=True)
    write_csv(report_dir / 'coverage_before.csv', ['label', 'count'], before)
    write_csv(report_dir / 'coverage_after_proposed.csv', ['label', 'count'], after)
    write_csv(report_dir / 'transitions.csv', ['before', 'after', 'count'],
              [{'before': a, 'after': b, 'count': n} for (a, b), n in sorted(transitions.items())])
    timestamp = datetime.now(timezone.utc).isoformat()
    charts(taxonomy, after, report_dir, run_id, timestamp, manifest['versions']['model'])
    candidate_count = sum(x['rule_status'] in ('unknown', 'needs_review') for x in records)
    processing = {status: sum(task['status'] == status for task in tasks.values())
                  for status in ('PENDING', 'RUNNING', 'RETRY_WAIT', 'PROPOSED', 'REVIEW_REQUIRED', 'FAILED')}
    processing['NOT_SELECTED'] = candidate_count - len(tasks)
    result = {'run_id': run_id, 'corpus_id': manifest['corpus_id'], 'timestamp': timestamp,
              'total': len(records), 'candidates': candidate_count, 'candidate_processing': processing,
              'cache_hits': sum(bool(task.get('cache_hit')) for task in tasks.values()),
              'tasks': summary['tasks'], 'api_calls': summary['api_calls'], 'unknown_usage': summary['unknown_usage'],
              'quota_requests_by_kind': summary['quota_requests_by_kind'],
              'usage_observed': summary['usage_observed'], 'estimated_cost': summary['estimated_cost'],
              'cost_basis': summary['cost_basis'], 'unknown_before': next(x['count'] for x in before if x['label'] == 'unknown'),
              'unknown_after': next(x['count'] for x in after if x['label'] == 'unknown'),
              'cloud_requires_review': not cloud_supported,
              'limitations': ['Suggested labels are not ground truth', 'Dedup follows baseline and may merge or split postings',
                              'Multi-position issues require human review', 'Rule labels are not audited',
                              'Gold evaluation may not represent all roles', 'External project usage is unknown']}
    (report_dir / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result
