"""Read-only extension progress and descriptive throughput; makes no API calls."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[1]
BASELINE_BATCH3 = {
    'attempts': 11991,
    'actual_input_output_tokens': 76563019,
    'first_to_last_request_start_seconds': 2950.748348236084,
    'actual_tokens_per_second': 25946.98360020037,
}


def summarize(data, freeze):
    plan = json.loads(freeze.read_text())
    selected = [r for r in plan['runs'] if
                r['config']['architecture'] == 'paper_reference' or
                (r['config']['architecture'] == 'bullet_memory' and
                 r['config']['repetition'] > plan['amendment']['prior_repeats'])]
    expected = plan['new_bullet_runs'] + plan['new_reference_runs']
    if len(selected) != expected or len({r['id'] for r in selected}) != expected:
        raise ValueError('Frozen extension IDs are incomplete or duplicated')
    ids = [r['id'] for r in selected]
    placeholders = ','.join('?' for _ in ids)
    db = sqlite3.connect(f'file:{(data / "experiments.sqlite").resolve()}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    now = time.time()
    # One short read transaction provides an internally consistent progress view.
    db.execute('BEGIN')
    runs = {r['id']: dict(r) for r in db.execute(
        f'SELECT id,status,error FROM runs WHERE id IN ({placeholders})', ids)}
    rounds = {r['run_id']: r['n'] for r in db.execute(
        f'SELECT run_id,COUNT(*) n FROM rounds WHERE run_id IN ({placeholders}) GROUP BY run_id', ids)}
    attempts = list(db.execute(
        f'SELECT run_id,created,status,cost,usage,raw_path FROM api_attempts '
        f'WHERE run_id IN ({placeholders}) ORDER BY created', ids))
    ledger = dict(db.execute("SELECT SUM(cost) spent, SUM(CASE WHEN status='pending' THEN reserved ELSE 0 END) reserved FROM api_attempts").fetchone())
    db.rollback()
    db.close()
    groups = defaultdict(list)
    for row in selected:
        groups[row['config']['architecture']].append(row)
    grouped = {}
    for architecture, rows in groups.items():
        counts = [rounds.get(r['id'], 0) for r in rows]
        grouped[architecture] = {
            'runs': len(rows), 'completed': sum(runs.get(r['id'], {}).get('status') == 'completed' for r in rows),
            'rounds_done': sum(counts), 'rounds_target': sum(r['config']['T'] for r in rows),
            'round_min': min(counts), 'round_max': max(counts),
            'statuses': dict(Counter(runs.get(r['id'], {}).get('status', 'not_created') for r in rows)),
        }
    statuses = Counter(r['status'] for r in attempts)
    tokens = Counter()
    http_errors = Counter()
    latest = {}
    for row in attempts:
        usage = json.loads(row['usage'] or '{}')
        for key in ('prompt_tokens', 'completion_tokens'):
            tokens[key] += usage.get(key, 0)
        latest[row['run_id']] = row
        # Inspect only unsuccessful raw responses, never print request/response text.
        if row['status'] not in ('accepted', 'pending') and row['raw_path']:
            raw_path = data / row['raw_path']
            if raw_path.exists():
                code = json.loads(raw_path.read_text()).get('http_status')
                if isinstance(code, int) and code >= 400:
                    http_errors[str(code)] += 1
    all_completed = all(runs.get(run, {}).get('status') == 'completed' for run in ids)
    start = attempts[0]['created'] if attempts else None
    last_start = attempts[-1]['created'] if attempts else None
    finish = None
    if all_completed:
        finish = max((data / row['raw_path']).stat().st_mtime for row in latest.values() if row['raw_path'])
    elapsed = max(0, (finish if finish is not None else now) - start) if start is not None else 0
    actual_tokens = sum(tokens.values())
    first_to_last = last_start - start if start is not None else 0
    comparable_tps = actual_tokens / first_to_last if first_to_last > 0 else None
    baseline_spent = plan['amendment']['balance']['spent']
    return {
        'observed_at_utc': datetime.fromtimestamp(now, timezone.utc).isoformat(),
        'all_completed': all_completed, 'extension_runs': len(ids),
        'by_architecture': grouped,
        'runs_with_errors': [r['id'] for r in runs.values() if r['error']],
        'attempt_statuses': dict(statuses), 'http_error_counts': dict(http_errors),
        'http_429_count': http_errors['429'],
        'starting_ledger_usd': baseline_spent,
        'ledger_spent_usd': ledger['spent'], 'ledger_reserved_usd': ledger['reserved'],
        'ledger_delta_usd': ledger['spent'] - baseline_spent,
        'selected_run_cost_usd': sum(r['cost'] for r in attempts),
        'first_request_utc': datetime.fromtimestamp(start, timezone.utc).isoformat() if start else None,
        'elapsed_seconds': elapsed, 'token_usage': dict(tokens),
        'actual_tokens_per_elapsed_second': actual_tokens / elapsed if elapsed else None,
        'performance_comparison': {
            'baseline_batch3': BASELINE_BATCH3,
            'extension_first_to_last_request_start_seconds': first_to_last,
            'extension_actual_tokens_per_start_span_second': comparable_tps,
            'ratio_to_baseline': comparable_tps / BASELINE_BATCH3['actual_tokens_per_second'] if comparable_tps else None,
            'interpretation': 'Descriptive only; workload, output lengths and service latency differ. In-progress usage excludes pending calls. Elapsed includes pauses; completed end is latest final-response file mtime.',
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'data/runs/live')
    parser.add_argument('--freeze', type=Path, default=ROOT / 'configs/extension-freeze.json')
    parser.add_argument('--out', type=Path, help='Optionally save JSON, e.g. reports/extension_execution.json')
    args = parser.parse_args()
    result = summarize(args.data, args.freeze)
    text = json.dumps(result, indent=2, allow_nan=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + '\n')
    print(text)


if __name__ == '__main__':
    main()
