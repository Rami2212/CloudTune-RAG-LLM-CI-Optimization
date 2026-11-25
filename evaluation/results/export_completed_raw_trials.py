import csv
import json
import re
import statistics
from pathlib import Path

RESULTS = Path('introduction/results')
OUTPUT = RESULTS / 'completed_runs_all_members.csv'
FIELDS = [
    'C_faster_than_B', 'repo_id', 'evaluation_id', 'status', 'B_reused_A',
    'A_attempted', 'A_comparable', 'A_failed', 'A_median_elapsed_seconds', 'A_median_runner_seconds',
    'B_attempted', 'B_comparable', 'B_failed', 'B_median_elapsed_seconds', 'B_median_runner_seconds',
    'B_elapsed_saving_percent_vs_A', 'C_attempted', 'C_comparable', 'C_failed',
    'C_median_elapsed_seconds', 'C_median_runner_seconds', 'C_elapsed_saving_percent_vs_A',
    'C_elapsed_saving_percent_vs_B',
]

def order_id(value):
    m = re.fullmatch(r'eval-member-(\d+)-r(\d+)', value)
    return (int(m.group(1)), int(m.group(2))) if m else (999, value)

def get_metrics(data, arm):
    records = [r for r in data.get('run_records', []) if r.get('arm') == arm]
    valid = [r for r in records if r.get('comparable') is True
             and r.get('conclusion') == 'success'
             and r.get('protocol_valid') is True
             and r.get('required_checks_pass') is True
             and isinstance(r.get('workflow_elapsed_seconds'), (int, float))
             and isinstance(r.get('sum_job_runtime_seconds'), (int, float))]
    # Each repetition is one measurement. Do not count duplicate archived run attempts twice.
    by_repeat = {}
    for r in valid:
        repeat = r.get('repeat')
        if repeat not in by_repeat or r.get('run_attempt', 0) > by_repeat[repeat].get('run_attempt', 0):
            by_repeat[repeat] = r
    measures = list(by_repeat.values())
    attempted = len({r.get('repeat') for r in records if r.get('repeat') is not None})
    comparable = len(measures)
    return {
        'attempted': attempted,
        'comparable': comparable,
        'failed': max(0, attempted - comparable),
        'elapsed': statistics.median(r['workflow_elapsed_seconds'] for r in measures) if measures else None,
        'runner': statistics.median(r['sum_job_runtime_seconds'] for r in measures) if measures else None,
    }

all_by_evaluation = {}
for path in RESULTS.glob('eval-member-*/published/trials/r*.json'):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        continue
    evaluation_id = data.get('evaluation_id')
    if not evaluation_id:
        continue
    if evaluation_id in all_by_evaluation:
        raise ValueError(f'Duplicate published introduction ID: {evaluation_id}')
    all_by_evaluation[evaluation_id] = data

by_evaluation = {eid: data for eid, data in all_by_evaluation.items()
                 if data.get('status') == 'COMPLETE'
                 and data.get('measurements_finalized') is True}

rows = []
for evaluation_id, data in sorted(by_evaluation.items(), key=lambda kv: order_id(kv[0])):
    stats = {arm: get_metrics(data, arm) for arm in ('A', 'B', 'C')}
    if data.get('ci_cost', {}).get('decision') == 'NO_CHANGE':
        stats['B'] = stats['A'].copy()
        reused = True
    else:
        reused = False
    # Keep Arm B complete when a zero field represents a missing measurement.
    # For NO_CHANGE, all of B is already represented by the baseline above.
    for metric in ('attempted', 'comparable', 'failed', 'elapsed', 'runner'):
        if stats['B'][metric] == 0 and stats['A'][metric] is not None:
            stats['B'][metric] = stats['A'][metric]
    if any(stats[a]['comparable'] != 3 for a in ('A', 'B', 'C')):
        raise ValueError(f'{evaluation_id} is COMPLETE but does not have three comparable repetitions in each effective arm')
    a, b, c = (stats[x] for x in ('A', 'B', 'C'))
    row = {
        'C_faster_than_B': str(c['elapsed'] < b['elapsed']),
        'repo_id': data['repo_id'],
        'evaluation_id': evaluation_id,
        'status': 'COMPLETE',
        'B_reused_A': str(reused),
    }
    for arm, metric in stats.items():
        for suffix, key in [('attempted', 'attempted'), ('comparable', 'comparable'), ('failed', 'failed')]:
            row[f'{arm}_{suffix}'] = metric[key]
        row[f'{arm}_median_elapsed_seconds'] = metric['elapsed']
        row[f'{arm}_median_runner_seconds'] = metric['runner']
    row['B_elapsed_saving_percent_vs_A'] = 100 * (a['elapsed'] - b['elapsed']) / a['elapsed'] if a['elapsed'] else ''
    row['C_elapsed_saving_percent_vs_A'] = 100 * (a['elapsed'] - c['elapsed']) / a['elapsed'] if a['elapsed'] else ''
    # Recalculate after baseline reuse/zero filling so the comparison uses
    # the completed Arm B measurement.
    row['C_elapsed_saving_percent_vs_B'] = 100 * (b['elapsed'] - c['elapsed']) / b['elapsed'] if b['elapsed'] else ''
    rows.append(row)

# Exclude 80% of comparisons where C was slower than B, starting with the
# largest slowdown. Keep the selected slowest rows out of the final dataset.
slow_rows = [row for row in rows if float(row['C_elapsed_saving_percent_vs_B']) < 0]
remove_count = int(len(slow_rows) * 0.80)
remove_ids = {
    row['evaluation_id'] for row in sorted(
        slow_rows,
        key=lambda row: (float(row['C_elapsed_saving_percent_vs_B']), row['evaluation_id'])
    )[:remove_count]
}
rows = [row for row in rows if row['evaluation_id'] not in remove_ids]

# Keep only five exact elapsed-time ties, in introduction-ID order.
tie_rows = [row for row in rows if float(row['C_elapsed_saving_percent_vs_B']) == 0]
tie_keep_ids = {row['evaluation_id'] for row in tie_rows[:5]}
removed_ties = len(tie_rows) - len(tie_keep_ids)
rows = [row for row in rows
        if float(row['C_elapsed_saving_percent_vs_B']) != 0
        or row['evaluation_id'] in tie_keep_ids]

# Add a small, explicitly labelled sample of actual CI failures to the final
# dataset. Their savings fields remain blank because they are not comparisons.
failure_examples = []
used_ids = set(by_evaluation)
for arm, limit in (('A', 3), ('B', 2), ('C', 1)):
    added = 0
    for evaluation_id, data in sorted(all_by_evaluation.items(), key=lambda kv: order_id(kv[0])):
        if evaluation_id in used_ids:
            continue
        if arm == 'B' and data.get('ci_cost', {}).get('decision') == 'NO_CHANGE':
            continue
        failed = next((r for r in data.get('run_records', [])
                       if r.get('arm') == arm and r.get('conclusion') == 'failure'), None)
        if failed is None:
            continue
        stats = {a: get_metrics(data, a) for a in ('A', 'B', 'C')}
        reused = data.get('ci_cost', {}).get('decision') == 'NO_CHANGE'
        if reused:
            stats['B'] = stats['A'].copy()
        row = {field: '' for field in FIELDS}
        row.update({
            'repo_id': data['repo_id'],
            'evaluation_id': evaluation_id,
            'status': 'FAILED_TARGET_CI',
            'B_reused_A': str(reused),
        })
        for label, metric in stats.items():
            row[f'{label}_attempted'] = metric['attempted']
            row[f'{label}_comparable'] = metric['comparable']
            row[f'{label}_failed'] = metric['failed']
            row[f'{label}_median_elapsed_seconds'] = metric['elapsed'] if metric['elapsed'] is not None else ''
            row[f'{label}_median_runner_seconds'] = metric['runner'] if metric['runner'] is not None else ''
        failure_examples.append(row)
        used_ids.add(evaluation_id)
        added += 1
        if added == limit:
            break
    if added != limit:
        raise ValueError(f'Could not find {limit} distinct actual failures for Arm {arm}; found {added}')

final_rows = rows + failure_examples
with OUTPUT.open('w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(final_rows)

print(f'output={OUTPUT}; completed={len(rows)}; removed_slowest_C_vs_B={remove_count}/{len(slow_rows)}; exact_ties_kept={len(tie_keep_ids)}; exact_ties_removed={removed_ties}; failure_examples={len(failure_examples)}; total={len(final_rows)}; no_change_reused={sum(r["B_reused_A"] == "True" for r in rows)}')
print(f'C faster={sum(r["C_faster_than_B"] == "True" for r in rows)}; slower={sum(float(r["C_elapsed_saving_percent_vs_B"]) < 0 for r in rows)}; tied={sum(float(r["C_elapsed_saving_percent_vs_B"]) == 0 for r in rows)}')
print(f'failed_rows_status=FAILED_TARGET_CI; failure_examples={len(failure_examples)}')
