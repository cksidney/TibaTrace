#!/usr/bin/env python3
"""Build the TibaTrace / Esenai Group branded compliance documents from reviewed Markdown.

Use the bundled Codex workspace Python runtime. This changes presentation only;
source approval decisions, evidence dates and technical identifiers are retained.
"""
from __future__ import annotations
import argparse, hashlib, json, math, re
from pathlib import Path
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.opc.constants import RELATIONSHIP_TYPE as RT

ROOT=Path(__file__).resolve().parents[2]
EDITION='2026-10-26'
PACK='TibaTrace_Esenai_Group_'+EDITION
OUT=ROOT/'output/docx'/PACK
ASSETS=ROOT/'docs/compliance/brand'
TMP=ROOT/'tmp/document-branding'
BLACK='000000'; NAVY='143455'; GRAY='586575'; RULE='D9D9D9'
FONT='Carlito'; MONO='DejaVu Sans Mono'
WIDTH=6.95
all_docs=[]
source_map={}

def clean(value):
    return str(value).replace('\u2011','-').replace('\u2013','-').replace('\u2014','-').replace('\u00a0',' ')

def plain(tokens):
    out=[]
    for t in tokens or []:
        if t['type']=='image':out.append(t.get('text',''))
        elif t.get('tokens'):out.append(plain(t['tokens']))
        elif t['type'] in ('br','html'):
            if re.search(r'<br\s*/?>',t.get('text',''),re.I):out.append('\n')
            elif t['type']=='html':out.append(re.sub('<[^>]*>','',t.get('text','')))
        else:out.append(t.get('text',''))
    return clean(''.join(out))

def props(run, size=None, bold=None, italic=None, color=None, mono=False):
    run.font.name=MONO if mono else FONT
    rf=run._element.get_or_add_rPr().get_or_add_rFonts()
    rf.set(qn('w:ascii'),run.font.name);rf.set(qn('w:hAnsi'),run.font.name)
    if size:run.font.size=Pt(size)
    if bold is not None:run.bold=bold
    if italic is not None:run.italic=italic
    run.font.color.rgb=RGBColor.from_string(color or BLACK)
    return run

def field(p,name):
    begin=OxmlElement('w:fldChar');begin.set(qn('w:fldCharType'),'begin')
    instr=OxmlElement('w:instrText');instr.set(qn('xml:space'),'preserve');instr.text=' '+name+' '
    sep=OxmlElement('w:fldChar');sep.set(qn('w:fldCharType'),'separate')
    txt=OxmlElement('w:t');txt.text='1'
    end=OxmlElement('w:fldChar');end.set(qn('w:fldCharType'),'end')
    # Separate result runs keep field fonts independent of the document's last body run.
    for element in (begin,instr,sep,txt,end):
        run=props(p.add_run(),size=8,color=GRAY)
        run._r.append(element)

def picture(p,path,width,alt,crop=None):
    run=p.add_run();shape=run.add_picture(str(path),width=Inches(width))
    if crop:
        l,t,r,b=crop
        shape.height=round(shape.height*((100000-t-b)/(100000-l-r)))
        rect=OxmlElement('a:srcRect')
        for key,value in zip(('l','t','r','b'),crop):rect.set(key,str(value))
        fill=shape._inline.graphic.graphicData.pic.blipFill
        fill.insert(1,rect)
    shape._inline.docPr.set('descr',alt)
    return shape

def hyperlink(p,text,url,size=10.5,bold=False,italic=False):
    rel=p.part.relate_to(url,RT.HYPERLINK,is_external=True)
    link=OxmlElement('w:hyperlink');link.set(qn('r:id'),rel)
    run=p.add_run();props(run,size=size,bold=bold,italic=italic,color=NAVY)
    under=OxmlElement('w:u');under.set(qn('w:val'),'single');run._r.get_or_add_rPr().append(under)
    run.text=clean(text);link.append(run._r);p._p.append(link)

def link_target(item,href):
    if href.startswith(('http://','https://','mailto:','#')):return href
    file,_,fragment=href.partition('#')
    resolved=(ROOT/item['sourcePath']).parent.joinpath(file).resolve()
    if resolved in source_map:
        dest=source_map[resolved]
        # DOCX and PDF folders have identical group/name layouts.
        import os
        relative=os.path.relpath(dest,OUT/item['group'])
        return relative+('#'+fragment if fragment else '')
    try:rel=resolved.relative_to(ROOT)
    except ValueError:return href
    return 'https://github.com/cksidney/TibaTrace/blob/codex/dpia-control-closure/'+rel.as_posix()+('#'+fragment if fragment else '')

def inlines(p,tokens,item,*,size=10.5,bold=False,italic=False):
    for t in tokens or []:
        kind=t['type']
        if kind=='strong':inlines(p,t.get('tokens'),item,size=size,bold=True,italic=italic)
        elif kind in ('em','del'):inlines(p,t.get('tokens'),item,size=size,bold=bold,italic=True)
        elif kind=='codespan':props(p.add_run(clean(t.get('text',''))),size=max(size-1,8),bold=bold,mono=True)
        elif kind=='link':hyperlink(p,plain(t.get('tokens')) or t.get('text',''),link_target(item,t['href']),size=size,bold=bold,italic=italic)
        elif kind=='br':p.add_run().add_break()
        elif kind=='html':
            if re.search(r'<br\s*/?>',t.get('text',''),re.I):p.add_run().add_break()
            else:
                content=re.sub('<[^>]*>','',t.get('text',''))
                if content:props(p.add_run(clean(content)),size=size,bold=bold,italic=italic)
        elif kind=='image':props(p.add_run(t.get('text','')),size=size,italic=True)
        elif t.get('tokens'):inlines(p,t['tokens'],item,size=size,bold=bold,italic=italic)
        elif kind in ('text','escape'):props(p.add_run(clean(t.get('text','')).replace('\n',' ')),size=size,bold=bold,italic=italic)
        else:raise ValueError('Unrecognized inline '+kind)


def set_cell_shading(cell,fill):
    tcpr=cell._tc.get_or_add_tcPr();x=OxmlElement('w:shd');x.set(qn('w:fill'),fill);tcpr.append(x)

def make_table(doc,t,item):
    heads=t['header'];rows=t['rows'];n=len(heads)
    scores=[]
    for i in range(n):
        values=[len(plain(row[i].get('tokens'))) for row in rows]
        h=plain(heads[i].get('tokens')).lower()
        if h=='#':score=0.25
        elif h in ('id','requirement id','result','status','current status'):score=0.8
        elif 'owner' in h or 'priority' in h:score=1.12
        else:score=min(3.4,max(1.2,math.sqrt((sum(values)/max(1,len(values)))/50)))
        scores.append(score)
    widths=[WIDTH*v/sum(scores) for v in scores]
    table=doc.add_table(rows=1,cols=n)
    table.alignment=WD_TABLE_ALIGNMENT.CENTER;table.autofit=False
    for col,width in zip(table.columns,widths):col.width=Inches(width)
    tblpr=table._tbl.tblPr
    borders=OxmlElement('w:tblBorders')
    for side in ('top','left','bottom','right','insideH','insideV'):
        x=OxmlElement('w:'+side);x.set(qn('w:val'),'single');x.set(qn('w:sz'),'4');x.set(qn('w:color'),RULE);borders.append(x)
    tblpr.append(borders)
    margin=OxmlElement('w:tblCellMar')
    for side in ('top','bottom','left','right'):
        x=OxmlElement('w:'+side);x.set(qn('w:w'),'95' if side in ('top','bottom') else '105');x.set(qn('w:type'),'dxa');margin.append(x)
    tblpr.append(margin)
    allrows=[heads]+rows
    for j,values in enumerate(allrows):
        row=table.rows[0] if j==0 else table.add_row()
        if j==0:
            x=OxmlElement('w:tblHeader');row._tr.get_or_add_trPr().append(x)
        if sum(len(plain(v.get('tokens'))) for v in values)<1100:
            row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for i,(cell,value,width) in enumerate(zip(row.cells,values,widths)):
            cell.width=Inches(width);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_shading(cell,NAVY if j==0 else ('F2F5F8' if j%2==0 else 'FFFFFF'))
            p=cell.paragraphs[0]
            p.paragraph_format.space_after=Pt(2);p.paragraph_format.space_before=Pt(2)
            p.paragraph_format.line_spacing=1.09;p.paragraph_format.keep_with_next=False
            p.paragraph_format.widow_control=True
            text=plain(value.get('tokens'))
            if len(text)<55 and (scores[i]<1.2 or n==2 and i==0):p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            inlines(p,value.get('tokens'),item,size=9.3 if n>=5 else 9.8,bold=j==0)
            if j==0:
                for run in p.runs:run.font.color.rgb=RGBColor(255,255,255)
    p=doc.add_paragraph();p.paragraph_format.space_after=Pt(3);p.paragraph_format.space_before=Pt(0);p.paragraph_format.line_spacing=0.35
    props(p.add_run(''),size=3)

def blocks(doc,tokens,item,level=0):
    for t in tokens:
        kind=t['type']
        if kind=='space':continue
        if kind=='heading':
            depth=t['depth'];text=plain(t.get('tokens'))
            # Titles and headings retain words, dates and qualifications with plain punctuation-free display.
            text=re.sub(r'[^\w\s]',' ',text);text=re.sub(r'\s+',' ',text).strip()
            if depth==1:
                p=doc.add_paragraph(text,style='Title')
                p.paragraph_format.space_after=Pt(9)
                sub=doc.add_paragraph('ESENAI GROUP LTD  |  '+('SYSTEM DOCUMENTATION' if item['group']=='system' else 'DHA EVIDENCE DOCUMENTATION'))
                sub.paragraph_format.space_after=Pt(13);props(sub.runs[0],size=8,bold=True)
            else:p=doc.add_paragraph(text,style='Heading '+str(min(depth-1,3)))
        elif kind in ('paragraph','text'):
            p=doc.add_paragraph()
            inlines(p,t.get('tokens') or [{'type':'text','text':t.get('text','')}],item)
        elif kind=='list':
            for index,entry in enumerate(t['items'],1):
                marker=str(t.get('start',1)+index-1)+'.' if t.get('ordered') else '\u2022'
                first=True
                for sub in entry['tokens']:
                    if sub['type'] in ('text','paragraph'):
                        p=doc.add_paragraph();p.paragraph_format.left_indent=Inches(.17+level*.18);p.paragraph_format.first_line_indent=Inches(-.17)
                        p.paragraph_format.space_after=Pt(4)
                        props(p.add_run(marker+' ' if first else ''),size=10.5)
                        inlines(p,sub.get('tokens') or [{'type':'text','text':sub.get('text','')}],item)
                        first=False
                    else:blocks(doc,[sub],item,level+1)
        elif kind=='table':make_table(doc,t,item)
        elif kind=='code':
            if t.get('lang','').lower()=='mermaid':
                image=ASSETS/'system-architecture.png'
                p=doc.add_paragraph();p.paragraph_format.keep_with_next=True
                picture(p,image,WIDTH,'TibaTrace system architecture. The exact Mermaid source is retained in the supplied Markdown.')
                cap=doc.add_paragraph('System architecture and trust boundaries')
                cap.paragraph_format.space_after=Pt(10);props(cap.runs[0],size=9,italic=True)
            else:
                for line in clean(t['text']).splitlines():
                    p=doc.add_paragraph();p.paragraph_format.space_after=Pt(1);p.paragraph_format.line_spacing=1.05
                    p.paragraph_format.left_indent=Inches(.10);p.paragraph_format.right_indent=Inches(.07)
                    sh=OxmlElement('w:shd');sh.set(qn('w:fill'),'F2F5F8');p._p.get_or_add_pPr().append(sh)
                    props(p.add_run(line or ' '),size=8.2,mono=True)
        elif kind=='blockquote':
            before=len(doc.paragraphs);blocks(doc,t['tokens'],item,level)
            for p in doc.paragraphs[before:]:p.paragraph_format.left_indent=Inches(.2)
        elif kind=='hr':doc.add_paragraph()
        elif kind=='html':
            text=re.sub('<[^>]*>','',t.get('text','')).strip()
            if text:doc.add_paragraph(clean(text))
        else:raise ValueError('Unrecognized block '+kind+' in '+item['name'])

def build(item):
    doc=Document();sec=doc.sections[0]
    sec.page_width=Inches(8.27);sec.page_height=Inches(11.69)
    sec.left_margin=sec.right_margin=Inches(.66);sec.top_margin=Inches(1.29);sec.bottom_margin=Inches(.65)
    sec.header_distance=Inches(.23);sec.footer_distance=Inches(.31)
    styles=doc.styles
    for name in ('Normal','Title','Subtitle','Heading 1','Heading 2','Heading 3','Header','Footer','Hyperlink'):
        if name not in styles:continue
        st=styles[name];st.font.name=FONT;st.font.color.rgb=RGBColor(0,0,0)
        rpr=st.element.get_or_add_rPr()
        for color in rpr.findall(qn('w:color')):
            for attr in ('themeColor','themeTint','themeShade'):color.attrib.pop(qn('w:'+attr),None)
    for node in list(styles.element.iter(qn('w:pBdr'))):node.getparent().remove(node)
    for name in ('Header','Footer'):styles[name].paragraph_format.tab_stops.clear_all()
    normal=styles['Normal'];normal.font.size=Pt(10.5)
    normal.paragraph_format.space_after=Pt(6);normal.paragraph_format.line_spacing=1.12;normal.paragraph_format.widow_control=True
    styles['Title'].font.size=Pt(22);styles['Title'].font.bold=True
    for i,size in enumerate((14,11.5,10.5),1):
        st=styles['Heading '+str(i)];st.font.size=Pt(size);st.font.bold=True
        st.paragraph_format.space_before=Pt(12 if i==1 else 9);st.paragraph_format.space_after=Pt(5);st.paragraph_format.keep_with_next=True
    # The native Word crop changes only the placement rectangle; source logo bytes remain untouched.
    header=sec.header.paragraphs[0];header.paragraph_format.space_after=Pt(0)
    header.paragraph_format.tab_stops.add_tab_stop(Inches(WIDTH),WD_TAB_ALIGNMENT.RIGHT)
    picture(header,ASSETS/'tibatrace-logo.jpeg',1.0,'TibaTrace logo',(8000,16000,8000,22000))
    header.add_run('\t');picture(header,ASSETS/'esenai-group-logo.png',1.35,'Esenai Group logo')
    tag=sec.header.add_paragraph('TibaTrace  |  Esenai Group Ltd')
    tag.paragraph_format.space_after=Pt(0);props(tag.runs[0],size=8,bold=True)
    identity='EG/TT/'+('SYS/'+item['name'][:2] if item['group']=='system' else 'DHA/'+str([x['name'] for x in all_docs if x['group']=='dha'].index(item['name'])+1).zfill(2))
    footer=sec.footer.paragraphs[0];footer.paragraph_format.tab_stops.add_tab_stop(Inches(WIDTH),WD_TAB_ALIGNMENT.RIGHT)
    props(footer.add_run(identity+'  |  Branding edition 26 October 2026'),size=8,color=GRAY)
    footer.add_run('\t');props(footer.add_run('Page '),size=8,color=GRAY);field(footer,'PAGE');props(footer.add_run(' of '),size=8,color=GRAY);field(footer,'NUMPAGES')
    doc.core_properties.author='Esenai Group Ltd';doc.core_properties.last_modified_by='Esenai Group Ltd'
    title=next(t for t in item['tokens'] if t['type']=='heading' and t['depth']==1)
    doc.core_properties.title=plain(title['tokens']);doc.core_properties.subject='TibaTrace system and DHA documentation'
    doc.core_properties.keywords='TibaTrace, Esenai Group Ltd, '+identity
    doc.core_properties.comments='Branding edition 26 October 2026. Approval status and source evidence dates retained.'
    blocks(doc,item['tokens'],item)
    path=source_map[(ROOT/item['sourcePath']).resolve()];path.parent.mkdir(parents=True,exist_ok=True);doc.save(path)
    text=' '.join(doc.element.body.itertext())
    return {'source':item['sourcePath'],'document_id':identity,'title':doc.core_properties.title,
        'docx':str(path.relative_to(ROOT)), 'source_sha256':hashlib.sha256((ROOT/item['sourcePath']).read_bytes()).hexdigest(),
        'docx_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_status_preserved':all(phrase not in json.dumps(item['tokens']) or phrase in text for phrase in ('NOT APPROVED','NOT_REASSESSED'))}


def main():
    global all_docs,source_map
    parser=argparse.ArgumentParser();parser.add_argument('--only',action='append',default=[]);args=parser.parse_args()
    all_docs=json.loads((TMP/'tokens.json').read_text())
    source_map={(ROOT/item['sourcePath']).resolve():OUT/item['group']/('TibaTrace_'+item['name'][:-3]+'.docx') for item in all_docs}
    results=[]
    for item in all_docs:
        if args.only and not any(s in item['name'] for s in args.only):continue
        results.append(build(item));print(item['group']+'/'+item['name'],flush=True)
    (TMP/('pilot-manifest.json' if args.only else 'BUILD_MANIFEST.json')).write_text(json.dumps({'edition':EDITION,'operator':'Esenai Group Ltd','product':'TibaTrace','documents':results},indent=2)+'\n')
    assert all(row['source_status_preserved'] for row in results)
    print('Built',len(results),'branded DOCX documents.')
if __name__=='__main__':main()
