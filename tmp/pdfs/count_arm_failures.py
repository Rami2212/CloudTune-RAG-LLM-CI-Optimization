import json
from collections import Counter, defaultdict
from pathlib import Path

root=Path('introduction/results')
docs=[]
for p in root.glob('eval-member-*/published/trials/r*.json'):
    try: d=json.loads(p.read_text(encoding='utf-8'))
    except Exception: continue
    if d.get('evaluation_id'):
        docs.append(d)

for scope, cohort in [('all',docs),('completed',[d for d in docs if d.get('status')=='COMPLETE'])]:
    print('\nSCOPE',scope,'evaluations',len(cohort))
    for arm in ('A','B','C'):
        attempts=[]; failed=[]; failed_repos=set(); failed_conclusions=Counter(); reasons=Counter()
        for d in cohort:
            decision=d.get('ci_cost',{}).get('decision') if arm=='B' else None
            if arm=='B' and decision=='NO_CHANGE':
                continue # no distinct B CI run was dispatched
            recs=[r for r in d.get('run_records',[]) if r.get('arm')==arm]
            for r in recs:
                attempts.append((d,r))
                ok=(r.get('comparable') is True and r.get('conclusion')=='success' and r.get('protocol_valid') is True and r.get('required_checks_pass') is True)
                if not ok:
                    failed.append((d,r)); failed_repos.add(d.get('evaluation_id'))
                    failed_conclusions[str(r.get('conclusion'))]+=1
                    reasons[str(r.get('failure_class') or ('protocol_invalid' if r.get('protocol_valid') is not True else 'required_checks_failed' if r.get('required_checks_pass') is not True else 'not_comparable'))]+=1
        print(arm,'attempted run_records',len(attempts),'failed run_records',len(failed),'repos with failure',len(failed_repos),'conclusions',dict(failed_conclusions),'reasons',dict(reasons))
    print('introduction statuses',dict(Counter(d.get('status') for d in cohort)))
