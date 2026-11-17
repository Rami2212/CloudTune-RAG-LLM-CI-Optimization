from pathlib import Path
import pandas as pd, numpy as np, json, hashlib
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
root=Path('outputs/evaluation_report')
d=pd.read_csv('completed_runs_all_members_80pct_faster.csv')
m=json.loads((root/'metrics.json').read_text())
# Validate all provided savings and the faster flag against source timings.
for col,a,b in [('B_elapsed_saving_percent_vs_A','B','A'),('C_elapsed_saving_percent_vs_A','C','A'),('C_elapsed_saving_percent_vs_B','C','B')]:
 calc=100*(d[b+'_median_elapsed_seconds']-d[a+'_median_elapsed_seconds'])/d[b+'_median_elapsed_seconds']
 mask=d[col].notna()
 assert np.allclose(d.loc[mask,col],calc[mask])
assert m['flags_mismatch']==0
assert (d.loc[d.B_attempted==0,'A_median_elapsed_seconds'].values==d.loc[d.B_attempted==0,'B_median_elapsed_seconds'].values).all()
doc=Document(); sec=doc.sections[0]
sec.top_margin=Inches(.7);sec.bottom_margin=Inches(.65);sec.left_margin=sec.right_margin=Inches(.75)
sec.page_width=Inches(8.27);sec.page_height=Inches(11.69)
for sn in ['Normal','Title','Subtitle','Heading 1','Heading 2']:
 s=doc.styles[sn];s.font.name='Calibri';s.font.color.rgb=RGBColor(0,0,0)
doc.styles['Normal'].font.size=Pt(11)
doc.styles['Normal'].paragraph_format.space_after=Pt(7)
doc.styles['Normal'].paragraph_format.line_spacing=1.08
doc.styles['Title'].font.size=Pt(25)
doc.styles['Heading 1'].font.size=Pt(16)
doc.styles['Heading 2'].font.size=Pt(12)
foot=sec.footer.paragraphs[0];foot.alignment=2
foot.add_run('CloudTune evaluation report  |  ')
fld=OxmlElement('w:fldSimple');fld.set(qn('w:instr'),'PAGE');foot._p.append(fld)
def p(t):doc.add_paragraph(t)
def h(t):doc.add_heading(t,1)
def table(head,rows,widths=None):
 t=doc.add_table(rows=1, cols=len(head));t.autofit=False
 if widths:
  for c,w in zip(t.columns,widths):c.width=Inches(w)
 for c,v in zip(t.rows[0].cells,head):c.text=str(v)
 repeat=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(repeat)
 for row in rows:
  for c,v in zip(t.add_row().cells,row):c.text=str(v)
 for i,row in enumerate(t.rows):
  for j,c in enumerate(row.cells):
   if widths:c.width=Inches(widths[j])
   tcpr=c._tc.get_or_add_tcPr()
   borders=OxmlElement('w:tcBorders')
   for edge in ['top','left','bottom','right']:
    el=OxmlElement('w:'+edge);el.set(qn('w:val'),'single');el.set(qn('w:sz'),'4');el.set(qn('w:color'),'D9D9D9');borders.append(el)
   tcpr.append(borders)
   shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'243C50' if i==0 else ('F1F4F6' if i%2==0 else 'FFFFFF'));tcpr.append(shade)
   margins=OxmlElement('w:tcMar')
   for edge in ['top','left','bottom','right']:
    el=OxmlElement('w:'+edge);el.set(qn('w:w'),'85');el.set(qn('w:type'),'dxa');margins.append(el)
   tcpr.append(margins);c.vertical_alignment=1
   for para in c.paragraphs:
    para.paragraph_format.space_after=Pt(2);para.paragraph_format.space_before=Pt(2)
    for run in para.runs:
     run.font.size=Pt(10)
     if i==0:run.bold=True;run.font.color.rgb=RGBColor(255,255,255)
 doc.add_paragraph().paragraph_format.space_after=Pt(0)
def page():doc.add_page_break()
doc.add_heading('CloudTune evaluation results',0)
p('Research meeting report   |   16 November 2026')
p('This report describes the 142 completed evaluations in the supplied CSV. Arm C has a lower recorded median elapsed time than Arm B in 114 of 142 rows, or 80.3%. This is the proportion of evaluations won, not an 80% reduction in execution time.')
p('Among the 75 rows with actual Arm B attempts and a populated C versus B savings field, C is faster in 59 cases, or 78.7%. The median reported reduction is 6.64%. The remaining 67 rows have zero B attempts, so their B timings must be distinguished from independently executed B measurements.')
h('Key results')
table(['Comparison','Rows','Faster  Equal  Slower','Median saving'],[
['B versus A',142,'24  /  76  /  42','0.00%'],
['C versus A',142,'103  /  6  /  33','5.68%'],
['C versus B with B attempts',75,'59  /  0  /  16','6.64%'],
['C versus B recorded timings',142,'114  /  0  /  28','6.98%*']], [2.35,.5,1.65,1.15])
p('*Calculated from the recorded timing columns across all rows, including the 67 rows with no B attempts. This is a descriptive comparison of stored values.')


h('Meeting interpretation')
p('The supplied subset favors C on elapsed time, including when B was executed. However, regressions remain: C is slower than A in 33 rows and slower than an executed B in 16 rows. These results support discussion of benefits and exceptions within this dataset, rather than a universal speedup claim.')
page()
h('Dataset scope and measurement coverage')
p('The CSV is the sole source of truth for this report. One row represents one evaluation ID and repository ID. There are 142 unique repositories, 142 unique evaluation IDs and 24 columns; every status is COMPLETE. Arms retain the source labels A, B and C because the CSV does not formally define their implementations.')
table(['Arm','Attempted runs','Comparable runs','Failed runs','Rows with attempts'],[
['A',426,426,0,142],['B',225,225,0,75],['C',426,426,0,142]], [1,1.4,1.45,1.1,1.7])
p('Across the supplied rows there are 1,077 attempted runs and 1,077 comparable runs. A and C each have three attempts per row. B has three attempts in 75 rows and zero attempts in 67 rows. No recorded failures occur in this completed subset; an overall experiment success rate cannot be inferred without omitted evaluations.')
h('Verdicts and timing availability')
table(['ci_cost_verdict','rag_verdict','Rows'],[
['PASS','PASS',64],['PASS','NO_CHANGE',11],['NO_CHANGE','PASS',51],['NO_CHANGE','NO_CHANGE',16]], [2.5,2.5,1.65])
p('The ci_cost_verdict field contains 75 PASS and 67 NO_CHANGE values; rag_verdict contains 115 PASS and 27 NO_CHANGE values. These verdicts are separate from measured speed: PASS does not itself mean faster, and NO_CHANGE does not establish identical observed timings.')
p('All 67 rows with zero B attempts have ci_cost_verdict equal to NO_CHANGE and B timing medians equal to A timing medians. Their C_elapsed_saving_percent_vs_B values are blank. This pattern is consistent with baseline timing reuse, but the CSV contains no measurement provenance field that independently confirms the mechanism.')
h('Data consistency checks')
p('No repository IDs or evaluation IDs are duplicated. There are 67 blank cells, all in C_elapsed_saving_percent_vs_B; every other field is populated. All nonblank supplied savings percentages agree with calculations from the corresponding elapsed medians within numerical precision. Every C_faster_than_B flag agrees with the recorded B and C elapsed medians.')
p('The file name is not used as evidence of a speedup or selection rule. The CSV does not describe how this completed subset was chosen or provide execution dates, workflow identities, model versions, cache states or raw repeat timings.')
page()
h('Elapsed time and runner time')
p('For each repository, elapsed saving is calculated as 100 × (reference median − comparison median) / reference median. Positive values indicate a reduction; negative values indicate a regression. Summary medians give equal weight to each repository.')
table(['Comparison','Mean saving','Median saving','Faster rows'],[
['B versus A  all rows','−3.35%','0.00%','24 / 142  16.9%'],
['C versus A  all rows','6.96%','5.68%','103 / 142  72.5%'],
['C versus B  B attempted','10.15%','6.64%','59 / 75  78.7%'],
['C versus B  zero B attempts*','9.19%','7.07%','55 / 67  82.1%']], [2.75,1,1,1.9])
p('*Derived comparison against stored B medians; no B runs were attempted in these rows. In the 75-row B-attempted group, the middle 50% of C versus B savings range from 2.26% to 17.21%.')
table(['Arm','Median elapsed seconds','Median runner seconds','Sum of elapsed medians','Sum of runner medians'],[
[a,f'{d[a+"_median_elapsed_seconds"].median():.1f}',f'{d[a+"_median_runner_seconds"].median():.1f}',f'{m["elapsed"][a]:,.0f}',f'{m["runner"][a]:,.0f}'] for a in 'ABC'], [.5,1.45,1.45,1.6,1.65])
p('Elapsed and runner fields measure different quantities and are analyzed separately. Across all rows, the sum of C elapsed medians is 1,207 seconds below A, a 7.19% reduction. The sum of C runner medians is 1,858 seconds below A, a 5.39% reduction. Relative to the recorded B medians, these reductions are 9.75% and 6.91%, respectively.')
p('Sums of medians are descriptive aggregates, not total measured run time or monetary savings. They include stored B values for rows without B attempts. Runner prices, billing rules and optimizer inference costs are absent, so a financial return cannot be calculated.')
h('Results by evaluation ID member group')
table(['Member group','Rows','C faster than B*','Median C saving*','B attempted rows'],[
[x[0].replace('member-',''),x[1],f'{x[2]} / {x[1]}',f'{x[3]:.2f}%',x[4]] for x in m['members']], [1.25,.55,1.65,1.55,1.65])
p('*Computed from recorded medians across all rows in each group. Groups are parsed from evaluation IDs. Different repository mixes and unequal group sizes prevent interpreting these summaries as member performance comparisons.')
page()
h('Examples and interpretation limits')
p('The following examples use only the 75 rows with B attempts and a populated C versus B saving. They show that the overall pattern includes both substantial improvements and regressions.')
for title,frame in [('Largest C improvements over B',d.nlargest(3,'C_elapsed_saving_percent_vs_B')),('Largest C regressions against B',d.nsmallest(3,'C_elapsed_saving_percent_vs_B'))]:
 doc.add_heading(title,2)
 table(['Repository','B seconds','C seconds','C saving'],[[r.repo_id,int(r.B_median_elapsed_seconds),int(r.C_median_elapsed_seconds),f'{r.C_elapsed_saving_percent_vs_B:.2f}%'] for _,r in frame.iterrows()],[3.6,.95,.95,1.15])
h('Limits on research claims')
p('These are descriptive results for a cleaned, completed subset. The CSV supplies neither the full attempted repository pool nor exclusion reasons, so it cannot establish generalization to that pool or an overall failure rate.')
p('Each row provides arm medians and counts, without the underlying three repeat timings. Within-repository variability, paired repeat behavior and sensitivity to run order cannot be examined. No statistical significance or causal attribution is claimed in this report.')
p('The data do not include an LLM-only arm, retrieved evidence, candidate changes or implementation metadata. They therefore cannot isolate the contribution of retrieval or explain which optimization mechanisms produced the observed differences.')
h('Recommended discussion points')
p('Use 78.7% wins and 6.64% median elapsed reduction for the C versus B comparison with actual B attempts. Present the 80.3% figure as the win share across recorded B timings, with the zero-attempt group clearly identified.')
p('Review the 16 C versus B regressions with B attempts and the 33 C versus A regressions. For a fuller research claim, obtain the complete evaluation roster, selection history, raw repeat timings and configuration metadata, while retaining this CSV unchanged as the source for the present report.')
h('Source and reproducibility')
p('Source file: completed_runs_all_members_80pct_faster.csv. All counts, comparisons and tables were computed directly from this file. No external document was used to establish results or arm identities. Percentages are rounded to two decimal places, except win shares shown to one decimal place.')
p('SHA256: '+hashlib.sha256(Path('completed_runs_all_members_80pct_faster.csv').read_bytes()).hexdigest())
doc.save(root/'CloudTune_Evaluation_Report.docx')
print(root/'CloudTune_Evaluation_Report.docx')

