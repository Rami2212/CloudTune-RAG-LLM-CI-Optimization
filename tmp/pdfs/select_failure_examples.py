import json
from pathlib import Path
root=Path('introduction/results')
allrows=[]
for p in sorted(root.glob('eval-member-*/published/trials/r*.json')):
 try:d=json.loads(p.read_text(encoding='utf-8'))
 except Exception:continue
 for r in d.get('run_records',[]):
  if r.get('conclusion')=='failure':
   allrows.append((d,r))
for arm,limit in [('A',3),('B',2),('C',1)]:
 print('\nARM',arm)
 selected=[]; seen=set()
 for d,r in allrows:
  if r.get('arm')!=arm or d.get('evaluation_id') in seen:continue
  if arm=='B' and d.get('ci_cost',{}).get('decision')=='NO_CHANGE':continue
  selected.append((d,r));seen.add(d.get('evaluation_id'))
  print(d.get('evaluation_id'),d.get('repo_id'),'status='+str(d.get('status')),'decision='+str((d.get('ci_cost') if arm=='B' else d.get('rag') if arm=='C' else {}).get('decision')),'run_id='+str(r.get('run_id')),'reason='+str(r.get('failure_class')))
  if len(selected)>=limit:break
 print('selected',len(selected))
