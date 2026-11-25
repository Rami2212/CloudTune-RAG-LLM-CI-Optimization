import json, statistics
from pathlib import Path

ROOT = Path('introduction/results')
ties=[]
for path in sorted(ROOT.glob('eval-member-*/published/trials/r*.json')):
    try: d=json.loads(path.read_text(encoding='utf-8'))
    except Exception: continue
    if d.get('status')!='COMPLETE' or d.get('measurements_finalized') is not True: continue
    vals={}
    byarm={}
    for arm in ('A','B','C'):
        rr=[r for r in d.get('run_records',[]) if r.get('arm')==arm and r.get('comparable') is True and r.get('conclusion')=='success' and r.get('protocol_valid') is True and r.get('required_checks_pass') is True]
        byarm[arm]=[r.get('workflow_elapsed_seconds') for r in rr]
        vv=[r.get('workflow_elapsed_seconds') for r in rr if isinstance(r.get('workflow_elapsed_seconds'),(int,float))]
        vals[arm]=statistics.median(vv) if vv else None
    if d.get('ci_cost',{}).get('decision')=='NO_CHANGE': vals['B']=vals['A']
    if vals['B'] is not None and vals['C'] is not None and vals['B']==vals['C']:
        ties.append((d,vals,byarm))

print('ties',len(ties))
from collections import Counter
print('B decisions',dict(Counter(x[0].get('ci_cost',{}).get('decision') for x in ties)))
print('C decisions',dict(Counter(x[0].get('rag',{}).get('decision') for x in ties)))
print('B reused A',sum(x[0].get('ci_cost',{}).get('decision')=='NO_CHANGE' for x in ties))
for d,v,raw in ties:
    print(d['evaluation_id'],d['repo_id'],'Bdecision='+str(d.get('ci_cost',{}).get('decision')),'Cdecision='+str(d.get('rag',{}).get('decision')),'A='+str(v['A']),'B='+str(v['B']),'C='+str(v['C']),'runs='+str(raw))
