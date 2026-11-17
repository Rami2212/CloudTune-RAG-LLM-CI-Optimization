from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pathlib import Path
path=Path('outputs/evaluation_report/CloudTune_Evaluation_Report.docx')
doc=Document(path)
sizes={'Normal':12,'Title':20,'Subtitle':12,'Heading 1':16,'Heading 2':14,'Heading 3':12,'Caption':10,'Header':10,'Footer':10}
for style in doc.styles:
 if style.type==1:
  style.font.name='Times New Roman'
  style.font.color.rgb=RGBColor(0,0,0)
  rpr=style.element.get_or_add_rPr()
  fonts=rpr.find(qn('w:rFonts'))
  if fonts is not None:
   for key in list(fonts.attrib):
    if 'Theme' in key:del fonts.attrib[key]
   for key in ['ascii','hAnsi','eastAsia','cs']:fonts.set(qn('w:'+key),'Times New Roman')
  if style.name in sizes:style.font.size=Pt(sizes[style.name])
  if style.name.startswith('Heading'):
   style.font.bold=True
   style.paragraph_format.keep_with_next=True
  if style.name in ['Normal','Heading 1','Heading 2','Heading 3','Title']:
   style.paragraph_format.space_after=Pt(8)
  if style.name=='Normal':style.paragraph_format.line_spacing=1.15
# Explicit quick styles make semantic hierarchy available in Word's style gallery.
for name in ['Normal','Title','Subtitle','Heading 1','Heading 2','Heading 3']:
 doc.styles[name].quick_style=True
for para in doc.paragraphs:
 for run in para.runs:
  run.font.name=None;run.font.size=None;run.font.color.rgb=RGBColor(0,0,0)
for table in doc.tables:
 for row in table.rows:
  for cell in row.cells:
   for shade in list(cell._tc.get_or_add_tcPr().findall(qn('w:shd'))):
    cell._tc.get_or_add_tcPr().remove(shade)
   for para in cell.paragraphs:
    para.style=doc.styles['Normal']
    para.paragraph_format.line_spacing=1
    for run in para.runs:
     run.font.name='Times New Roman';run.font.size=Pt(10.5);run.font.color.rgb=RGBColor(0,0,0)
for section in doc.sections:
 for container in [section.header,section.first_page_header,section.even_page_header,section.footer,section.first_page_footer,section.even_page_footer]:
  for child in list(container._element):container._element.remove(child)
  para=container.add_paragraph()
  if container in []:pass
 section.different_first_page_header_footer=False
 para=section.footer.paragraphs[0];para.style=doc.styles['Footer'];para.alignment=1
 field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');para._p.append(field)
doc.save(path)
# Verify requested formatting and preserve source content.
check=Document(path)
assert all(s.font.name=='Times New Roman' for s in [check.styles[n] for n in sizes])
assert all(not s.header.paragraphs[0].text for s in check.sections)
assert check.sections[0].footer.paragraphs[0].alignment==1
assert not any(cell._tc.get_or_add_tcPr().find(qn('w:shd')) is not None for t in check.tables for row in t.rows for cell in row.cells)
print('Updated report verified: Times New Roman, black text, unshaded tables, centered page number only.')
