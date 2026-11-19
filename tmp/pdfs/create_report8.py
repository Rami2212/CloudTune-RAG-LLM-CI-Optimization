from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4

ROOT = Path.cwd()
OUT = ROOT / 'output/pdf/SE_2021_038_Milestone_2_PReport8.pdf'
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='ReportTitle', fontName='Times-Bold', fontSize=16, leading=20, alignment=TA_CENTER, spaceAfter=18))
styles.add(ParagraphStyle(name='BodyReport', fontName='Times-Roman', fontSize=11, leading=16, spaceAfter=9))
styles.add(ParagraphStyle(name='SectionReport', fontName='Times-Bold', fontSize=12.5, leading=17, spaceBefore=11, spaceAfter=9, keepWithNext=True))
styles.add(ParagraphStyle(name='TaskReport', fontName='Times-Bold', fontSize=11, leading=15, spaceBefore=9, spaceAfter=6, keepWithNext=True))
styles.add(ParagraphStyle(name='SmallReport', fontName='Times-Roman', fontSize=9.5, leading=13, spaceAfter=7))
story=[]
def p(t, style='BodyReport'): story.append(Paragraph(t, styles[style]))
def h(t): p(t,'SectionReport')
def task(title, body, evidence):
    p(title, 'TaskReport'); p(body); p('<b>Evidence:</b> '+evidence, 'SmallReport')
def table(data, widths):
    cells=[[Paragraph(str(c),styles['SmallReport']) for c in row] for row in data]
    t=Table(cells,colWidths=widths,hAlign='LEFT',repeatRows=1)
    t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eeeeee')),('BOX',(0,0),(-1,-1),0.5,colors.grey),('INNERGRID',(0,0),(-1,-1),0.35,colors.lightgrey),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
    story.append(t); story.append(Spacer(1,8))
def new(): story.append(PageBreak())

p('Monthly Progress Report 8','ReportTitle')
p('<b>Student Name:</b> Iddamalgoda I. H. R. P.')
p('<b>Student ID:</b> SE/2021/038 &nbsp;&nbsp;&nbsp; <b>Group:</b> Group 06')
p('<b>Reporting period:</b> Current reporting month')
p('<b>Research title:</b> Repository-Aware CI Workflow Optimization Using LLMs and Research-Grounded RAG')
p('This month, my research focus changed from the CloudHeal framework implementation described in Report 7 to optimizing GitHub Actions workflows. The current study compares original workflows, the rule-based CI-Cost optimizer, and repository-aware RAG + LLM recommendations using repeated CI executions.')
h('1 Tasks Completed This Month')
task('Task 1 Revision of the research direction',
     'Revised the research questions, objectives, and contributions around three outcomes: CI execution efficiency, optimization applicability, and execution reliability. The study now investigates whether research-grounded recommendations reduce active workflow time and runner use compared with original workflows and CI-Cost.',
     'Updated research overview, research questions, objectives, contributions, and literature-gap analysis.')
task('Task 2 Literature review and pattern organization',
     'Organized a catalog of 16 CI optimization patterns from five research papers. The catalog includes caching, cancellation of obsolete work, change filtering, timeout selection, test selection and prioritization, environment reuse, and build configuration improvements. Recorded source citations, applicability conditions, limitations, and three code examples per pattern.',
     'Current 16-pattern catalog, results summary, and citations explaining how each source supports the study.')
task('Task 3 Repository dataset preparation',
     'Prepared repository candidates from the GitHub Actions workflow-history dataset. Retained 54,758 unique records, filtered these to 46,068 recently updated candidates, and sampled 5,000 repositories. Reserved 500 development candidates and selected 4,000 introduction candidates from the remaining pool, divided into four assignments of 1,000.',
     'Dataset preparation documentation, sampling manifests, and fixed introduction assignments.')

new()
h('1 Tasks Completed This Month continued')
task('Task 4 RAG knowledge preparation and candidate generation',
     'Implemented the pipeline to validate knowledge records, build retrieval documents, create BGE-M3 embeddings, and retrieve relevant evidence from Supabase pgvector. The generator receives the workflow, bounded repository context, and retrieved evidence through OpenRouter, then returns an APPLY or NO_CHANGE decision. Retrieval preparation does not fine-tune the language model.',
     'Dataset builder, embedding and retrieval components, structured candidate responses, and archived request and response records.')
p('The documented embedding configuration uses normalized 1,024-dimensional vectors, 1,024-token chunks with 128-token overlap, and the top five retrieved chunks. The existing frozen corpus manifest contains 74 documents, including 25 pattern documents and 49 example documents. Aligning that earlier corpus with the current 16-pattern research catalog remains necessary before claiming that introduction uses only those 16 patterns.', 'SmallReport')
task('Task 5 Three-arm introduction pipeline',
     'Implemented A as the original workflow, B as pinned and source-corrected CI-Cost, and C as RAG + LLM. Pinned repository snapshots and isolated fork branches support comparison. The pipeline adds a common manual-dispatch harness when required, validates candidates, generates each optimization once, and reuses it across three repetitions. Arm B NO_CHANGE cases reuse A measurements instead of dispatching duplicate trials.',
     'Candidate validation, fork preparation, dispatch execution, checkpointing, raw run evidence, and comparison exports.')
task('Task 6 Execution reliability and result reporting',
     'Added resumable batches, configurable batch names and repository ranges, existing-fork reuse, and handling for recoverable repository-level failures. Queue waits exceeding two minutes and individual in-progress trials exceeding ten minutes trigger cancellation requests and movement to the next repository. Increased the LLM request timeout to 300 seconds. Prepared repository-level CSV results and recomputed C-versus-B savings after baseline reuse.',
     'Batch controls, timeout and checkpoint records, failure reasons, and completed-result datasets.')
p('Evaluation flow','TaskReport')
for label in [
    'Screen repository and pin source workflow and context',
    'Prepare A original workflow   |   Generate B CI-Cost   |   Generate C RAG + LLM',
    'Apply shared validation and prepare common fork dispatch harness',
    'Run three repetitions per distinct variant and archive job timings',
    'Reuse A evidence for B NO_CHANGE and compare repository medians',
]:
    t=Table([[Paragraph(label,styles['SmallReport'])]],colWidths=[475])
    t.setStyle(TableStyle([('BOX',(0,0),(-1,-1),0.5,colors.grey),('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f5f5f5')),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    story.append(t)
    if not label.startswith('Reuse'): story.append(Spacer(1, 6))

new()
h('2 Hours Invested')
p('Total hours: ____________________')
table([['Activity','Hours','Work covered'],['Research and literature review','________','Research revision, pattern catalog, source mapping, and gaps.'],['Implementation and experiments','________','RAG pipeline, A/B/C execution, debugging, and result preparation.'],['Documentation and meetings','________','Research documents, progress reporting, and team coordination.']], [160,55,260])
h('3 Deliverables Produced')
for t in [
    'Revised research title, questions, objectives, contributions, and literature gaps.',
    'Catalog of 16 literature-derived patterns with source mapping and code examples.',
    'Repository dataset preparation process and four fixed introduction assignments.',
    'RAG dataset preparation, embedding, retrieval, and structured generation pipeline.',
    'A/B/C introduction pipeline with fork execution, validation, timing, and resumable batches.',
    'Completed-result exports with elapsed-time and runner-time comparisons.',
    'Updated setup, methodology, dataset, results, and citation documentation.'
]: p('- '+t)
h('4 Progress Against Plan')
p('The research scope, repository sampling process, knowledge pipeline, and comparative introduction implementation have been established. Hosted CI executions have produced completed comparison records, while blocked, failed, timed-out, and interrupted cases are recorded separately. The overall 4,000-repository assignment is not claimed as completed.')
p('The original implementation plan has been replaced by the CI optimization study. Work remains on reconciling the frozen corpus with the 16-pattern catalog, documenting configuration changes across resumed batches, consolidating all introduction outcomes, and completing the final analysis and paper.')
p('<b>Measurement approach:</b> Active workflow time counts periods when at least one job runs, counting overlapping jobs once. Runner time sums individual job durations, including concurrent jobs separately. Initial queue delay and local retrieval or generation latency are reported separately. Per-repository medians are calculated from comparable successful repetitions.')
p('<b>Savings formula:</b> 100 x (baseline median - candidate median) / baseline median. Runner time is a resource-use proxy; monetary VM cost was not directly measured from billing evidence.')

new()
h('5 Challenges Encountered')
table([['Challenge','Response and remaining work'],['Inconsistent LLM responses and API timeouts','Clarified structured decision requirements, archived generation failures, and extended the request timeout to 300 seconds.'],['Workflows without manual dispatch and existing research forks','Prepared a common dispatch harness and reused verified forks; retained checkpoint and branch identity checks.'],['Baseline failures, long queues, and invalid timing records','Recorded failure reasons, applied per-trial queue and execution limits, and added repository-level skip handling.'],['Windows GPU and file-access issues','Investigated device naming and CUDA-enabled PyTorch requirements; retained resumable checkpoints for interrupted work.'],['Documentation and experiment consistency','Identified the 16-pattern catalog versus 25-pattern frozen-corpus mismatch and the need to track code, model, prompt, and configuration revisions.']], [165,310])

h('6 Deviations from Plan')
p('The principal deviation is the change from CloudHeal framework implementation to repository-aware CI optimization. The revised study emphasizes a source-linked optimization knowledge base and repeated GitHub Actions measurements against two comparison arms.')
p('The introduction uses three arms only; an LLM-only arm is excluded. Consequently, the study evaluates the combined RAG + LLM method without isolating the contribution of retrieval. CI-Cost no-change outcomes reuse baseline evidence, and successful CI completion provides limited evidence of behavior preservation rather than proof of full functional equivalence.')
p('Batch resumption supports changes to code and configuration. Final reporting must identify those versions and any resulting protocol differences.')
new()
h('7 Next Month Goals')
for t in [
    'Align the retrieval corpus, index, and documentation with the approved 16-pattern catalog, retaining the provenance of earlier experiments.',
    'Continue introduction and consolidate completed, failed, blocked, timed-out, and no-change outcomes across all four assignments.',
    'Audit paired timings and baseline reuse, report slower and tied outcomes, and calculate uncertainty intervals for repository-level effects.',
    'Separate active workflow savings, runner-use savings, queue delay, and candidate-generation overhead in the analysis.',
    'Complete the methodology, results, limitations, and discussion sections of the research paper.'
]: p('- '+t)
h('8 Support Needed')
p('Supervisor feedback is needed on the revised questions, the corpus alignment plan, the treatment of no-change arms, and interpretation of the complete introduction outcomes. Guidance is also needed on statistical reporting and the limits of estimating VM cost from runner time.')
h('Research Sources')
p('The optimization catalog draws on Bouzenia and Pradel (2024), Jin and Servant (2021), Zheng et al. (2024), Gallaba et al. (2022), and Aidasso et al. (2025). Repository metadata comes from Cardoen et al. (2024) and the 2026 Zenodo dataset release. Lewis et al. (2020) informs the RAG approach; Chen et al. (2024) supports BGE-M3. Empirical reporting and uncertainty methods draw on Kitchenham et al. (2002), Jedlitschka and Pfahl (2005), and Efron and Tibshirani (1986).', 'SmallReport')

peers = [
    ('Hiruni Ramanayaka', 'SE/2021/024', [
        ('Contribution Quality', '5', 'Contributed to implementing the GitHub Middleware as part of the framework development.'),
        ('Commitment &amp; Effort', '4', 'Contributed to the assigned GitHub Middleware implementation work.'),
        ('Collaboration', '5', 'Worked on a framework component that is relevant to integration with the application.'),
        ('Reliability', '4', 'Followed through on assigned development work.'),
        ('Initiative', '4', 'Supported progress on the shared middleware component.')],
     'A cooperative team member who supported middleware development.',
     'Helped move the GitHub Middleware feature forward.',
     'Could provide frequent updates on task progress during the meetings to improve visibility of progress across the team.'),
    ('Ishara Danushan', 'SE/2021/027', [
        ('Contribution Quality', '5', 'Assisted with the GitHub Middleware implementation.'),
        ('Commitment &amp; Effort', '5', 'Showed consistent commitment to the assigned work.'),
        ('Collaboration', '4', 'Worked with peers to keep middleware tasks aligned.'),
        ('Reliability', '4', 'Handled assigned responsibilities dependably.'),
        ('Initiative', '4', 'Contributed to resolving implementation needs as they arose.')],
     'A reliable contributor who maintained good commitment to development tasks.',
     'Stayed engaged with the middleware implementation work.',
     'Could provide more frequent updates on individual progress during collaborative tasks to improve visibility of work across the team.'),
    ('Isuru kaweesha', 'SE/2021/001', [
        ('Contribution Quality', '4', 'Made a useful contribution to the GitHub Middleware feature.'),
        ('Commitment &amp; Effort', '5', 'Put good effort into assigned development activities.'),
        ('Collaboration', '5', 'Collaborated effectively on the shared implementation.'),
        ('Reliability', '4', 'Completed assigned work with a responsible approach.'),
        ('Initiative', '4', 'Helped identify practical ways to move development forward.')],
     'A proactive team member who collaborated well on middleware development.',
     'Contributed ideas and worked constructively with the team.',
     'Could provide frequent updates on framework development activities to improve visibility of the contribution to research activities.'),
]
for name, student_id, ratings, assessment, strength, improvement in peers:
    comments = [
        'Contributed to data preparation, literature review, and RAG results activities.',
        'Supported the shared work on research data, literature, and RAG results.',
        'Collaborated with the team on data preparation, literature review, and results.',
        'Contributed to the shared research preparation and results work.',
        'Supported progress on the revised CI optimization research.'
    ]
    ratings = [(criterion, rating, comment)
               for (criterion, rating, _), comment in zip(ratings, comments)]
    assessment = 'A collaborative team member who contributed to data preparation, literature review, and RAG results for the revised CI optimization research.'
    strength = 'Helped prepare research data and supported the literature review and RAG results work.'
    improvement = 'Could provide more frequent progress updates and document individual contributions to data preparation, literature review, and results.'
    if student_id == 'SE/2021/024':
        comments = [
            'Contributed to preparing research data, reviewing literature, and supporting RAG results.',
            'Put effort into the shared data preparation and results activities.',
            'Worked with the team on literature review and research preparation.',
            'Supported the research through contributions to data and results work.',
            'Helped move the revised research preparation forward.'
        ]
        assessment = 'A cooperative team member who supported the revised research through data preparation, literature review, and RAG results.'
        strength = 'Contributed to preparing research data while supporting the literature and results activities.'
        improvement = 'Could provide more regular updates on data preparation and results progress.'
    elif student_id == 'SE/2021/027':
        comments = [
            'Supported the literature review alongside data preparation and RAG results.',
            'Contributed effort to the research preparation and results work.',
            'Participated in the shared literature, data, and results activities.',
            'Helped advance the team\'s research preparation work.',
            'Supported progress across the revised research activities.'
        ]
        assessment = 'A collaborative contributor who helped with literature review, data preparation, and RAG results for the new research direction.'
        strength = 'Supported the literature review and contributed to the related data preparation and results work.'
        improvement = 'Could document literature findings and their relevance to the research more clearly.'
    else:
        comments = [
            'Contributed to RAG results activities, research data preparation, and literature review.',
            'Put effort into the shared results and research preparation tasks.',
            'Worked with peers on preparing data and supporting the RAG results process.',
            'Supported the team through contributions to the revised research work.',
            'Helped maintain progress on data, literature, and results activities.'
        ]
        assessment = 'A supportive team member who contributed to RAG results, data preparation, and literature review as the research direction changed.'
        strength = 'Helped with RAG results activities while contributing to data preparation and literature review.'
        improvement = 'Could keep clearer records of results activities and share observations with the team.'
    ratings = [(criterion, rating, comment)
               for (criterion, rating, _), comment in zip(ratings, comments)]
    new()
    p('Peer Evaluation Forms CONFIDENTIAL', 'ReportTitle')
    p('<b>Student Name:</b> Iddamalgoda I. H. R. P.')
    p('<b>Student ID:</b> SE/2021/038')
    p('<b>Group:</b> Group 06')
    p('<b>Reporting period:</b> Current reporting month')
    p('<b>Team member:</b> '+name+' ('+student_id+')', 'TaskReport')
    table([['Criterion', 'Rating (1-5)', 'Comments'], *ratings], [135,75,265])
    p('Overall Assessment', 'TaskReport')
    p(assessment)
    p('What did this team member do particularly well?', 'TaskReport')
    p(strength)
    p('What could this team member improve?', 'TaskReport')
    p(improvement)

def footer(c,d):
    c.setFont('Times-Roman',9)
    c.drawString(60,30,'SE/2021/038 | Group 06 | Progress Report 8')
    c.drawRightString(A4[0]-60,30,str(d.page))
doc=SimpleDocTemplate(str(OUT),pagesize=A4,rightMargin=60,leftMargin=60,topMargin=48,bottomMargin=48,title='Monthly Progress Report 8',author='Iddamalgoda I. H. R. P.')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT)
