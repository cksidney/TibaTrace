#!/usr/bin/env python3
"""Package visually approved TibaTrace / Esenai Group DOCX/PDF exports."""
import hashlib
import html
import json
import shutil
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

ROOT=Path(__file__).resolve().parents[2]
TMP=ROOT/'tmp/document-branding'
NAME='TibaTrace_Esenai_Group_Branded_Documents_2026-10-26'
TARGET=ROOT/'output'/NAME
manifest=json.loads((TMP/'BUILD_MANIFEST.json').read_text())
renders={r['source']:r for r in json.loads((TMP/'RENDER_MANIFEST.json').read_text())['documents']}
content=json.loads((TMP/'CONTENT_QA.json').read_text())
layout=json.loads((TMP/'LAYOUT_QA.json').read_text())
assert not content['omissions'] and not layout['issues']
visual=json.loads((TMP/'VISUAL_QA.json').read_text())
assert visual['pages_reviewed']==len(layout['pages']) and visual['result']=='PASS'
TARGET.mkdir(parents=True,exist_ok=True)
assert len(manifest['documents'])==35

for row in manifest['documents']:
    source=ROOT/row['source'];docx=ROOT/row['docx'];render=renders[row['source']]
    assert hashlib.sha256(source.read_bytes()).hexdigest()==row['source_sha256']
    assert hashlib.sha256(docx.read_bytes()).hexdigest()==row['docx_sha256']
    group=source.parent.name
    word=TARGET/'Word'/group/docx.name;word.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(docx,word)
    pdf=TARGET/'PDF'/group/(docx.stem+'.pdf');pdf.parent.mkdir(parents=True,exist_ok=True)
    reader=PdfReader(ROOT/render['pdf']);writer=PdfWriter();writer.clone_document_from_reader(reader)
    # Only paired-document link destinations change; page content streams remain identical.
    for page in writer.pages:
        for annotation in page.get('/Annots',[]):
            item=annotation.get_object();action=item.get('/A')
            if not action:continue
            action=action.get_object()
            for key in ('/URI','/F'):
                value=action.get(key)
                if value and str(value).lower().endswith('.docx'):
                    action[NameObject(key)]=TextStringObject(str(value)[:-5]+'.pdf')
    writer.add_metadata({'/Author':'Esenai Group Ltd','/Title':row['title'],'/Subject':'TibaTrace compliance documentation branding edition 26 October 2026'})
    with pdf.open('wb') as output:writer.write(output)
    check=PdfReader(pdf)
    assert len(check.pages)==render['pages']
    for a,b in zip(reader.pages,check.pages):
        assert a.get_contents().get_data()==b.get_contents().get_data(),'PDF layout content changed during link update'
    pdf_standalone=ROOT/'output/pdf/TibaTrace_Esenai_Group_2026-10-26'/group/pdf.name
    pdf_standalone.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(pdf,pdf_standalone)
    source_dest=TARGET/'Sources'/group/source.name;source_dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,source_dest)
    row.update(word=str(word.relative_to(TARGET)),pdf=str(pdf.relative_to(TARGET)),pages=render['pages'],pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())

shutil.copytree(ROOT/'docs/compliance/brand',TARGET/'Sources/brand',dirs_exist_ok=True)
shutil.copytree(ROOT/'docs/compliance/brand',TARGET/'Brand',dirs_exist_ok=True)
shutil.copy2(ROOT/'docs/compliance/dha/DHA_REQUIREMENTS_CATALOGUE.yaml',TARGET/'Sources/dha/DHA_REQUIREMENTS_CATALOGUE.yaml')
readme='''# TibaTrace and Esenai Group document pack

Branding edition: 26 October 2026.

This pack contains 35 system-compliance and DHA documents in editable Word and
print-ready PDF formats, together with their Markdown sources, the historical
requirements catalogue and the supplied brand assets. Open `START_HERE.html` for
the document index. Word and PDF folders share the same document grouping.

Both supplied logos appear in the page headers. The documents use consistent
black headings, table styles, document IDs, company metadata and page numbering.
All 110 rendered pages were checked. Content checks covered 2,423 paragraphs,
headings, code blocks and table cells without omissions. The architecture source
is retained alongside the rendered diagram. Technical identifiers, source paths,
certificate references, assessment dates and decisions are preserved.

Branding does not change document approval. The DPIA remains NOT APPROVED, policies
that were drafts remain drafts, and historical assessments keep their original
release/evidence boundaries. Current server deployment evidence is rc75, recorded
in the current register, technical delivery and owner action documents. This pack
supersedes earlier exports for presentation; it is a review copy, not an approved
regulatory submission. Private evidence, credentials and patient records are not
included. Source links outside this pack open the repository or original source.
'''
(TARGET/'README.md').write_text(readme)
rows=[]
for row in manifest['documents']:
    rows.append('<tr><td>'+html.escape(row['document_id'])+'</td><td>'+html.escape(row['title'])+'</td><td>'+str(row['pages'])+'</td><td><a href="'+html.escape(row['word'])+'">Word</a> &nbsp; <a href="'+html.escape(row['pdf'])+'">PDF</a></td></tr>')
index='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TibaTrace and Esenai Group document pack</title><style>body{font:16px/1.55 Arial,sans-serif;color:#172b42;max-width:1100px;margin:40px auto;padding:0 24px;background:#fff}header{display:flex;align-items:center;justify-content:space-between;margin-bottom:32px}header img:first-child{width:155px}header img:last-child{width:210px}h1{color:#000;font-size:30px;margin:0 0 12px}p{max-width:880px}table{border-collapse:collapse;width:100%;margin-top:28px;font-size:14px}th,td{padding:13px 15px;border:1px solid #d9d9d9;text-align:left}th{background:#143455;color:#fff}tr:nth-child(even){background:#f2f5f8}a{color:#143455}td:last-child{white-space:nowrap}.note{padding:16px 20px;background:#f2f5f8;border-radius:8px}footer{margin:28px 0;font-size:13px;color:#586575}</style><header><img src="Brand/tibatrace-logo.jpeg" alt="TibaTrace"><img src="Brand/esenai-group-logo.png" alt="Esenai Group"></header><h1>TibaTrace system and DHA documents</h1><p>Esenai Group Ltd · Branding edition 26 October 2026</p><p>35 documents · Editable Word and PDF copies · 110 reviewed pages</p><p class="note">The original approval decisions and evidence dates remain controlling. The system DPIA remains <strong>Not Approved</strong>. Historical assessments retain their original scope. Start with the current document register and owner evidence checklist.</p><table><thead><tr><th>Document ID</th><th>Document</th><th>Pages</th><th>Open</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table><footer>Technical paths and original evidence references are preserved. See README.md and MANIFEST.json for scope and file hashes.</footer></html>'''
(TARGET/'START_HERE.html').write_text(index)
manifest.update(branding_edition='2026-10-26',documents_count=35,total_rendered_pages=sum(r['pages'] for r in manifest['documents']),approval_status='NOT APPROVED; original document statuses retained',visual_review='All rendered pages reviewed; no visible layout defects remaining',content_checks=content['paragraph_heading_code_and_cell_checks'])
(TARGET/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
checksums=[]
for path in sorted(TARGET.rglob('*')):
    if path.is_file() and path.name!='SHA256SUMS':checksums.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.relative_to(TARGET).as_posix())
(TARGET/'SHA256SUMS').write_text('\n'.join(checksums)+'\n')
archive=ROOT/'output'/(NAME+'.zip')
with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=8) as z:
    for p in sorted(TARGET.rglob('*')):
        if p.is_file():z.write(p,str(Path(NAME)/p.relative_to(TARGET)))
with ZipFile(archive) as z:assert z.testzip() is None
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'word_documents':len(list((TARGET/'Word').rglob('*.docx'))),'pdf_documents':len(list((TARGET/'PDF').rglob('*.pdf'))),'rendered_pages':manifest['total_rendered_pages']},indent=2))
