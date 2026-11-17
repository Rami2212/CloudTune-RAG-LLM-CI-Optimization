import pandas as pd, numpy as np, json
d=pd.read_csv('completed_runs_all_members_80pct_faster.csv')
out={}
for name,x in [('all',d),('executed_B',d[d.B_attempted>0]),('reused_B',d[d.B_attempted==0])]:
 v=100*(x.B_median_elapsed_seconds-x.C_median_elapsed_seconds)/x.B_median_elapsed_seconds
 out[name]={'n':len(x),'wins':int((v>0).sum()),'ties':int((v==0).sum()),'losses':int((v<0).sum()),'median':v.median(),'mean':v.mean(),'q1':v.quantile(.25),'q3':v.quantile(.75)}
for pair in ['BA','CA','CB']:
 a,b=pair[0],pair[1]
 v=100*(d[b+'_median_elapsed_seconds']-d[a+'_median_elapsed_seconds'])/d[b+'_median_elapsed_seconds']
 out[pair]={'wins':int((v>0).sum()),'ties':int((v==0).sum()),'losses':int((v<0).sum()),'median':v.median(),'mean':v.mean(),'weighted':100*(d[b+'_median_elapsed_seconds'].sum()-d[a+'_median_elapsed_seconds'].sum())/d[b+'_median_elapsed_seconds'].sum()}
out['flags_mismatch']=int((d.C_faster_than_B != (d.C_median_elapsed_seconds<d.B_median_elapsed_seconds)).sum())
out['runner']={a:float(d[a+'_median_runner_seconds'].sum()) for a in 'ABC'}
out['elapsed']={a:float(d[a+'_median_elapsed_seconds'].sum()) for a in 'ABC'}
out['members']=[]
for member,x in d.groupby(d.evaluation_id.str.extract(r'(member-\d+)',expand=False)):
 v=100*(x.B_median_elapsed_seconds-x.C_median_elapsed_seconds)/x.B_median_elapsed_seconds
 out['members'].append([member,len(x),int((v>0).sum()),float(v.median()),int((x.B_attempted>0).sum())])
print(json.dumps(out,indent=2))
open('outputs/evaluation_report/metrics.json','w').write(json.dumps(out,indent=2))
