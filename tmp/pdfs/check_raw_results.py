import json
import statistics
from pathlib import Path

ROOT = Path('introduction/results')

def summarized(path: Path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('status') != 'COMPLETE' or not data.get('measurements_finalized'):
        return None
    records = data.get('run_records', [])
    arms = {}
    for arm in ('A', 'B', 'C'):
        vals = [float(r['workflow_elapsed_seconds']) for r in records
                if r.get('arm') == arm and r.get('comparable') is True
                and r.get('conclusion') == 'success'
                and r.get('protocol_valid') is True
                and r.get('required_checks_pass') is True
                and isinstance(r.get('workflow_elapsed_seconds'), (int, float))]
        arms[arm] = statistics.median(vals) if vals else None
    if data.get('ci_cost', {}).get('decision') == 'NO_CHANGE':
        arms['B'] = arms['A']
    if arms['B'] is None or arms['C'] is None or arms['B'] <= 0:
        return None
    saving_pct = 100 * (arms['B'] - arms['C']) / arms['B']
    return data, arms, saving_pct

def cohort(member=None):
    files = sorted((ROOT / f'eval-member-{member:02d}' if member else ROOT).glob(
        f'**/published/trials/r*.json'))
    # Deduplicate publication copies by introduction ID; prefer the canonical published trial.
    by_id = {}
    for path in files:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        eid = data.get('evaluation_id')
        if eid:
            by_id[eid] = path
    results = [summarized(p) for p in by_id.values()]
    results = [r for r in results if r]
    problems = []
    for eid, path in by_id.items():
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if d.get('status') != 'COMPLETE' or not d.get('measurements_finalized'):
            continue
        recs = d.get('run_records', [])
        def valid_count(arm):
            return len([r for r in recs if r.get('arm') == arm and r.get('comparable') is True and r.get('conclusion') == 'success' and r.get('protocol_valid') is True and r.get('required_checks_pass') is True])
        b_no_change = d.get('ci_cost', {}).get('decision') == 'NO_CHANGE'
        expected = [('A',3),('C',3)] + ([] if b_no_change else [('B',3)])
        bad = [(a,n,valid_count(a)) for a,n in expected if valid_count(a) != n]
        if bad:
            problems.append((eid, bad))
    wins = [r for r in results if r[2] > 0]
    losses = [r for r in results if r[2] < 0]
    ties = [r for r in results if r[2] == 0]
    print(f'cohort={member or "all"} raw_trial_files={len(files)} unique_evaluations={len(by_id)} paired_complete={len(results)}')
    print(f'faster={len(wins)} ({100*len(wins)/len(results):.2f}%) slower={len(losses)} ({100*len(losses)/len(results):.2f}%) tied={len(ties)}')
    if results:
        print(f'mean_repo_saving_pct={statistics.mean(r[2] for r in results):.2f}% median_repo_saving_pct={statistics.median(r[2] for r in results):.2f}%')
    print('status counts and excluded reason tallies:')
    all_data = []
    for path in by_id.values():
        try: all_data.append(json.loads(path.read_text(encoding='utf-8')))
        except Exception: pass
    from collections import Counter
    print(dict(Counter(d.get('status') for d in all_data)))
    print(f'B_NO_CHANGE_with_complete_pair={sum(r[0].get("ci_cost",{}).get("decision")=="NO_CHANGE" for r in results)}')
    print(f'complete_records_missing_three_valid_repeats={len(problems)}')
    if problems[:5]: print('examples',problems[:5])

cohort()
cohort(2)
