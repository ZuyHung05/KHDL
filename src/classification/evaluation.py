"""Offline gold evaluation. A gate is never opened on missing or unreviewed evidence."""
from collections import Counter
import json
import math
import re
from pathlib import Path

import yaml

from .dataset import ROOT
from .validation import SPECIAL


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def evaluate(predictions, gold, expected_ids, responses_received, schema_valid_responses,
             development_set=False, inputs=None, external_cloud=None, sampling_probabilities=None,
             unrepresented_groups=0):
    taxonomy = yaml.safe_load((ROOT / 'configs/role_taxonomy.yaml').read_text(encoding='utf-8'))
    roles = [role for family in taxonomy.values() for role in family] + sorted(SPECIAL)
    allowed = set(roles)
    g = {row['jd_id']: row for row in gold}
    p = {row['jd_id']: row for row in predictions}
    if len(g) != len(gold) or len(p) != len(predictions):
        raise ValueError('Duplicate JD ID in predictions or gold')
    if set(g) != set(expected_ids):
        raise ValueError('Gold IDs must exactly match the independent pilot sample')
    if not set(p).issubset(g):
        raise ValueError('Prediction ID outside pilot sample')
    if sampling_probabilities is not None:
        if set(sampling_probabilities) != set(expected_ids) or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or not 0 < value <= 1 for value in sampling_probabilities.values()):
            raise ValueError('Invalid or incomplete pilot inclusion probabilities')
    matrix = {role: Counter() for role in roles}
    weighted_matrix = {role: Counter() for role in roles}
    weighted_accepted = weighted_correct = 0.0
    accepted = correct_accepted = 0
    review = 0
    invalid_accepted = False
    cloud_counterexamples = 0
    cloud_false_positive = 0
    cloud_counterexamples_untested = 0
    for jd_id, row in g.items():
        if row.get('role') not in allowed:
            raise ValueError('Invalid gold role')
        annotations = row.get('annotations')
        if not isinstance(annotations, list) or len(annotations) != 2 or len({x.get('annotator') for x in annotations}) != 2 or not all(x.get('annotator') and x.get('blind') is True and x.get('guideline_version') and x.get('role') in allowed for x in annotations):
            raise ValueError('Gold requires two independent blind annotations with guideline version')
        if not row.get('adjudicated') or not row.get('adjudicator') or not isinstance(row.get('evidence'), list):
            raise ValueError('Gold requires adjudication, adjudicator and evidence')
        if (row.get('seniority') not in {'intern', 'junior', 'mid', 'senior', 'lead', 'manager', 'unknown'}
                or not isinstance(row.get('multiple_roles'), bool) or not isinstance(row.get('ambiguous'), bool)):
            raise ValueError('Gold requires seniority, ambiguity and multiple-role flags')
        if row['multiple_roles'] and row['role'] != 'unknown':
            raise ValueError('Multiple independent roles must be gold unknown')
        if inputs is None or jd_id not in inputs:
            raise ValueError('Frozen input is required to verify gold and predictions')
        item = inputs[jd_id]
        evidence_targets = set()
        for ev in row['evidence']:
            if not isinstance(ev, dict) or ev.get('target') not in ('primary_role', 'seniority') or ev.get('field') not in ('title', 'description', 'requirements') or not isinstance(ev.get('quote'), str) or not ev['quote'] or ev['quote'] not in item[ev['field']]:
                raise ValueError('Gold evidence does not match frozen input')
            evidence_targets.add(ev['target'])
        if (row['role'] != 'unknown' and 'primary_role' not in evidence_targets) or (row['seniority'] != 'unknown' and 'seniority' not in evidence_targets):
            raise ValueError('Gold role or seniority evidence is missing')
        pred = p.get(jd_id, {})
        result = pred.get('suggested') or {}
        if pred.get('status') == 'PROPOSED' and (not result or result.get('review_required') is not False or pred.get('validation_status') != 'VALID'):
            raise ValueError('Proposed task must contain a valid, non-review proposal')
        if result:
            from .validation import validate
            try:
                validate(result, item)
            except ValueError as exc:
                raise ValueError('Prediction failed independent validation') from exc
        # Missing, refused or failed responses are unresolved, not an explicit
        # model abstention. Treating them as unknown inflates unknown-class F1.
        label = result.get('primary_role') if result else 'unresolved'
        if label not in allowed and label != 'unresolved':
            raise ValueError('Invalid predicted role')
        matrix[row['role']][label] += 1
        weight = 1 / sampling_probabilities[jd_id] if sampling_probabilities is not None else 1.0
        weighted_matrix[row['role']][label] += weight
        is_accepted = pred.get('status') == 'PROPOSED' and result.get('review_required') is False
        if is_accepted:
            accepted += 1
            correct_accepted += label == row['role']
            weighted_accepted += weight
            if label == row['role']:
                weighted_correct += weight
            invalid_accepted |= pred.get('validation_status') != 'VALID'
        else:
            review += 1
        if row.get('cloud_counterexample') is True:
            if row['role'] != 'non_it':
                raise ValueError('Cloud counterexample must have non_it gold')
            cloud_counterexamples += 1
            cloud_text = ' '.join(item[field] for field in ('title', 'description', 'requirements'))
            if not result or not re.search(r'(?i)\b(?:aws|azure|gcp|google cloud|amazon web services|microsoft cloud)\b', cloud_text):
                cloud_counterexamples_untested += 1
            cloud_false_positive += label == 'Cloud'
    if external_cloud:
        cloud_counterexamples += external_cloud['count']
        cloud_false_positive += external_cloud['errors']
        cloud_counterexamples_untested += external_cloud['untested']
    metrics = {}
    for role in roles:
        tp = matrix[role][role]
        support = sum(matrix[role].values())
        predicted = sum(matrix[other][role] for other in roles)
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[role] = {'precision': precision, 'recall': recall, 'f1': f1, 'support': support}
    supported = [m['f1'] for m in metrics.values() if m['support']]
    macro = sum(supported) / len(supported) if supported else 0.0
    precision = correct_accepted / accepted if accepted else 0.0
    schema_rate = schema_valid_responses / responses_received if responses_received else 0.0
    complete = (len(expected_ids) == 200 and set(p) == set(expected_ids)
                and all(row.get('status') in ('PROPOSED', 'REVIEW_REQUIRED') for row in p.values()))
    checks = {'complete_independent_pilot': complete and not development_set,
              'all_accepted_valid': not invalid_accepted,
              'schema_rate_at_least_098': schema_rate >= .98,
              'macro_f1_at_least_080': macro >= .80,
              'accepted_precision_at_least_090': precision >= .90,
              'cloud_counterexample_tested_and_passed': cloud_counterexamples > 0 and cloud_false_positive == 0 and cloud_counterexamples_untested == 0}
    weighted = None
    if sampling_probabilities is not None:
        weighted_metrics = {}
        for role in roles:
            tp = weighted_matrix[role][role]
            support = sum(weighted_matrix[role].values())
            predicted = sum(weighted_matrix[other][role] for other in roles)
            w_precision = tp / predicted if predicted else 0.0
            w_recall = tp / support if support else 0.0
            w_f1 = 2 * w_precision * w_recall / (w_precision + w_recall) if w_precision + w_recall else 0.0
            weighted_metrics[role] = {'precision': w_precision, 'recall': w_recall, 'f1': w_f1,
                                      'estimated_input_group_support': support}
        w_supported = [row['f1'] for row in weighted_metrics.values() if row['estimated_input_group_support']]
        weighted = {'metrics': weighted_metrics,
                    'macro_f1_supported_classes': sum(w_supported) / len(w_supported) if w_supported else 0.0,
                    'accepted_precision': weighted_correct / weighted_accepted if weighted_accepted else 0.0,
                    'estimated_input_groups': sum(sum(row.values()) for row in weighted_matrix.values()),
                    'unrepresented_input_groups': unrepresented_groups,
                    'interpretation': 'Descriptive inverse-probability ratio estimates for represented input-hash strata after smoke; not JD-level estimates, no confidence intervals, and not used for the deployment gate.'}
    return {'sample_count': len(g), 'metrics': metrics, 'macro_f1_supported_classes': macro,
            'missing_gold_classes': [role for role in roles if not metrics[role]['support']],
            'accepted_precision': precision, 'accepted': accepted, 'review_or_unresolved': review,
            'response_count': responses_received, 'schema_valid_response_count': schema_valid_responses,
            'schema_valid_rate': schema_rate, 'cloud_counterexamples': cloud_counterexamples,
            'cloud_counterexample_errors': cloud_false_positive,
            'cloud_counterexamples_untested': cloud_counterexamples_untested,
            'cloud_requires_review': metrics['Cloud']['support'] < 20,
            'confusion_matrix': {role: {label: matrix[role][label] for label in roles + ['unresolved']} for role in roles},
            'weighted_group_estimates': weighted, 'gate_checks': checks, 'full_gate': all(checks.values())}


def assess_cloud_counterexamples(predictions, gold, inputs):
    """Evaluate an independent, human-labelled set using existing run outputs."""
    if not gold or any(row.get('cloud_counterexample') is not True or row.get('role') != 'non_it' for row in gold):
        raise ValueError('Cloud test set must contain only flagged non-IT gold cases')
    ids = [row['jd_id'] for row in gold]
    result = evaluate(predictions, gold, ids, 0, 0, inputs=inputs)
    return {'count': result['cloud_counterexamples'], 'errors': result['cloud_counterexample_errors'],
            'untested': result['cloud_counterexamples_untested']}


def plot_confusion(result, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    matrix = result['confusion_matrix']
    labels = list(matrix)
    predicted_labels = list(next(iter(matrix.values())))
    values = [[matrix[a][b] for b in predicted_labels] for a in labels]
    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(values, cmap='Blues')
    ax.set_xticks(range(len(predicted_labels)), predicted_labels, rotation=60, ha='right')
    ax.set_yticks(range(len(labels)), labels)
    ax.set(xlabel='Proposed role', ylabel='Gold role', title='Pilot confusion matrix')
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)
