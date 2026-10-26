"""Validate content preservation, logo metadata and page bounds before visual review."""
import importlib.util,json,re
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E
root=Path(__file__).resolve().parents[2];tmp=root/'tmp/document-branding'
spec=importlib.util.spec_from_file_location('branding',root/'scripts/docs/build_compliance_pack.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
manifest=json.loads((tmp/'BUILD_MANIFEST.json').read_text());tokens=json.loads((tmp/'tokens.json').read_text())
lookup={x['source']:x for x in manifest['documents']}
normalize=lambda text:re.sub(r'[^\w]','',text).casefold()
issues=[];checks=0

def check(tokens,body,source):
 global checks
 for t in tokens:
  kind=t['type']
  if kind=='code' and t.get('lang')=='mermaid':continue
  if kind in ('heading','paragraph','text','code'):
   text=b.plain(t.get('tokens')) if t.get('tokens') else t.get('text','')
   if text.strip():
    checks+=1
    if normalize(text) not in body:issues.append({'source':source,'kind':kind,'text':text[:140]})
  if kind=='list':
   for item in t['items']:check(item['tokens'],body,source)
  if kind=='blockquote':check(t['tokens'],body,source)
  if kind=='table':
   for row in [t['header']]+t['rows']:
    for cell in row:
     text=b.plain(cell.get('tokens'));checks+=1
     if normalize(text) not in body:issues.append({'source':source,'kind':'table','text':text[:140]})
for source in tokens:
 target=lookup[source['sourcePath']]
 with ZipFile(root/target['docx']) as z:
  tree=E.fromstring(z.read('word/document.xml'))
  body=normalize(''.join(tree.itertext()))
  check(source['tokens'],body,source['sourcePath'])
report={'documents':len(tokens),'paragraph_heading_code_and_cell_checks':checks,'omissions':issues,'mermaid_source':'Preserved in source Markdown; rendered as an architecture diagram.'}
(tmp/'CONTENT_QA.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
assert not issues

import json,re
from pathlib import Path
from zipfile import ZipFile
import pdfplumber
from lxml import etree as E
root=Path(__file__).resolve().parents[2];tmp=root/'tmp/document-branding'
manifest=json.loads((tmp/'RENDER_MANIFEST.json').read_text())
issues=[];pages=[]
ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','wp':'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'}
for row in manifest['documents']:
 docx=root/row['docx']
 with ZipFile(docx) as z:
  core=z.read('docProps/core.xml').decode();assert 'Esenai Group Ltd' in core
  header=E.fromstring(z.read('word/header1.xml'))
  assert len(header.findall('.//wp:docPr',ns))==2
  assert not E.fromstring(z.read('word/styles.xml')).findall('.//w:pBdr',ns)
 with pdfplumber.open(root/row['pdf']) as pdf:
  assert len(pdf.pages)==row['pages']
  for number,page in enumerate(pdf.pages,1):
   text=page.extract_text() or ''
   assert 'TibaTrace' in text and 'Esenai Group Ltd' in text
   footer=''.join(c['text'] for c in page.chars if c['top']>page.height-45)
   assert 'Page' in text and str(number) in footer and str(len(pdf.pages)) in footer,(row['source'],number,'page field')
   assert len(page.images)>=2
   bad=[c for c in page.chars if c['x0']<-1 or c['x1']>page.width+1 or c['top']<0 or c['bottom']>page.height+1]
   if bad:issues.append({'document':row['source'],'page':number,'outside_page_chars':len(bad)})
   body=[c for c in page.chars if c['top']>88 and c['bottom']<page.height-34]
   if body and max(c['bottom'] for c in body)>page.height-44:issues.append({'document':row['source'],'page':number,'body_close_to_footer':True})
   pages.append({'document':row['source'],'page':number,'characters':len(text),'images':len(page.images),'path':str((root/row['render_dir']/f'page-{number}.png').relative_to(root))})
(tmp/'LAYOUT_QA.json').write_text(json.dumps({'documents':len(manifest['documents']),'pages':pages,'issues':issues},indent=2)+'\n')
print(json.dumps({'documents':len(manifest['documents']),'pages':len(pages),'issues':issues},indent=2))
