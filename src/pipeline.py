"""Project CLI for the single maintained preparation pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.preparation.pipeline import run

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / 'data/inputs/legacy_import_20261127.parquet'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest='command', required=True)
    prepare = command.add_parser('prepare', help='Classify, deduplicate and report on explicit inputs')
    prepare.add_argument('--input', action='append', type=Path, default=[],
                         help='Imported Parquet or crawler jobs.jsonl; repeatable')
    prepare.add_argument('--run-id', required=True)
    prepare.add_argument('--execute', action='store_true', help='Write a new immutable result')
    command.add_parser('status', help='List completed preparation runs')
    args = parser.parse_args(argv)
    if args.command == 'status':
        base = ROOT / 'data/curated/preparation'
        results = []
        for path in sorted(base.glob('*/manifest.json')):
            manifest = json.loads(path.read_text(encoding='utf-8'))
            results.append({'run_id': manifest['run_id'], 'counts': manifest['counts'],
                            'created_at': manifest['created_at']})
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    paths = tuple(args.input or [DEFAULT_INPUT])
    run(ROOT, args.run_id, execute=args.execute, inputs=paths)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
