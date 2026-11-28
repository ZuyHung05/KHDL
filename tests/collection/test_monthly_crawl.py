import json

from src.collection.monthly_crawl import main, prepare_snapshot


def test_monthly_snapshot_prepares_only_unique_downloaded_jds(tmp_path):
    job = {
        'site': 'itviec', 'job_url': 'https://itviec.com/it-jobs/cloud-engineer-123',
        'title': 'Cloud Engineer', 'company': 'Acme', 'location': 'Ho Chi Minh',
        'description': 'Job Description\nOperate cloud infrastructure.\nCandidate Requirements\nAWS',
        'duties': 'Operate cloud infrastructure and build cloud services.',
        'requirements': 'AWS and Terraform experience.', 'parse_status': 'structured',
    }
    path = tmp_path/'jobs.jsonl'
    path.write_text('\n'.join(json.dumps(row) for row in (job, {**job, 'job_url': job['job_url']+'?ref=x'}))+'\n')
    stats = prepare_snapshot(path, tmp_path)
    assert stats['downloaded_descriptions'] == 2
    assert stats['eligible_primary_roles'] == {'Cloud': 1}
    assert stats['status']['eligible'] == 1
    assert (tmp_path/'prepared/eligible.csv').is_file()


def test_monthly_dry_run_needs_no_dataset_or_browser(tmp_path):
    assert main(['--out-dir', str(tmp_path), '--dry-run']) == 0
    plan = json.loads((tmp_path/'plan.json').read_text())
    assert plan['sources'] == ['topcv', 'itviec']
    assert plan['pages_per_role'] == 2
