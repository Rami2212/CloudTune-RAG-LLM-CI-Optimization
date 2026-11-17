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
p('Comparison of Arms B and C')
p('This report summarizes the comparison of Arms B and C across the 142 repository evaluations in the supplied CSV. C has a lower recorded median elapsed time than B in 114 evaluations, or 80.3%. This percentage describes the share of evaluations won, rather than the percentage reduction in execution time.')
p('In the 75 evaluations where B was attempted, C is faster in 59 cases, or 78.7%, with a median elapsed time reduction of 6.64%. The other 67 evaluations record zero B attempts and are reported separately.')
h('Evaluation coverage')
table(['Measure','Arm B','Arm C'],[
['Repository evaluations',142,142],
['Evaluations with attempts',75,142],
['Attempted runs',225,426],
['Comparable runs',225,426],
['Recorded failed runs',0,0],
['PASS verdicts',75,115],
['NO_CHANGE verdicts',67,27]], [3.65,1.5,1.5])
p('The dataset contains 142 unique repository IDs and 142 unique evaluation IDs. Every row has status COMPLETE. B records three attempts in 75 evaluations and zero attempts in 67 evaluations. C records three attempts in every evaluation. Together, B and C account for 651 attempted runs in this CSV.')
h('Elapsed time comparison')
table(['Comparison group','Rows','C faster','C slower','Median saving'],[
['B attempted',75,'59  78.7%','16  21.3%','6.64%'],
['Zero B attempts',67,'55  82.1%','12  17.9%','7.07%'],
['All recorded timings',142,'114  80.3%','28  19.7%','6.98%']], [2.1,.5,1.25,1.25,1.05])
p('There are no equal elapsed medians between B and C. The all-row and zero-attempt summaries are calculated from recorded timing columns. The CSV leaves C_elapsed_saving_percent_vs_B blank for all 67 zero-attempt B evaluations; those rows do not represent independently executed B comparisons.')
p('For the 75 evaluations with B attempts, mean C elapsed saving is 10.15%, and the middle 50% of savings range from 2.26% to 17.21%. Positive savings mean C is faster; negative savings mean C is slower.')
page()
h('Timing summaries')
p('The following summaries cover all 142 recorded rows. B values include the 67 evaluations with zero B attempts.')
table(['Metric','Arm B','Arm C'],[
['Median of repository elapsed medians in seconds','74.5','72.0'],
['Median of repository runner medians in seconds','130.5','101.5'],
['Sum of repository elapsed medians in seconds','17,268','15,584'],
['Sum of repository runner medians in seconds','35,051','32,629']], [3.65,1.5,1.5])
p('Across the recorded values, the sum of C elapsed medians is 1,684 seconds lower than B, a 9.75% reduction. The sum of C runner medians is 2,422 seconds lower, a 6.91% reduction. Sums of medians are descriptive aggregates and do not represent total measured execution time or monetary savings.')
h('Repository examples')
p('These examples are drawn from the 75 evaluations with actual B attempts and a populated C versus B savings field.')
for title,frame in [('Largest C improvements over B',d.nlargest(3,'C_elapsed_saving_percent_vs_B')),('Largest C regressions against B',d.nsmallest(3,'C_elapsed_saving_percent_vs_B'))]:
 doc.add_heading(title,2)
 table(['Repository','B seconds','C seconds','C saving'],[[r.repo_id,int(r.B_median_elapsed_seconds),int(r.C_median_elapsed_seconds),f'{r.C_elapsed_saving_percent_vs_B:.2f}%'] for _,r in frame.iterrows()],[3.6,.95,.95,1.15])
h('Source and calculation')
p('Source: completed_runs_all_members_80pct_faster.csv. All results in this report were calculated from this CSV. No local results folder was used. This report presents only the B versus C comparison.')
p('Elapsed saving percent = 100 × (B median elapsed seconds − C median elapsed seconds) / B median elapsed seconds. Each repository has equal weight in the mean and median savings summaries. Win shares use the number of rows in the stated comparison group.')
p('All 75 populated C versus B savings values agree with the timing-based calculation, and all 142 C_faster_than_B flags agree with the recorded medians.')
doc.save(root/'CloudTune_Evaluation_Report.docx')
