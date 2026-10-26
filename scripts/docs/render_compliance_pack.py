import argparse,concurrent.futures,json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2];tmp=root/'tmp/document-branding'
manifest=json.loads((tmp/'BUILD_MANIFEST.json').read_text())
parser=argparse.ArgumentParser(description='Render every branded DOCX with the canonical packaged renderer.')
parser.add_argument('--renderer',type=Path,required=True)
renderer=parser.parse_args().renderer.resolve(strict=True)
def run(row):
 p=root/row['docx'];out=tmp/'render'/p.parent.name/p.stem
 out.mkdir(parents=True,exist_ok=True)
 with (out/'render.log').open('w') as log:
  proc=subprocess.run([sys.executable,str(renderer),str(p),'--output_dir',str(out),'--emit_pdf','--width','1000'],stdout=log,stderr=subprocess.STDOUT)
 if proc.returncode:raise RuntimeError(str(out/'render.log'))
 pages=sorted(out.glob('page-*.png'),key=lambda p:int(p.stem.split('-')[1]))
 assert pages
 return {'source':row['source'],'docx':row['docx'],'render_dir':str(out.relative_to(root)),'pages':len(pages),'pdf':str((out/(p.stem+'.pdf')).relative_to(root))}
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
 futures=[executor.submit(run,row) for row in manifest['documents']]
 for f in concurrent.futures.as_completed(futures):
  result=f.result();results.append(result);print(result['source'],result['pages'],'pages',flush=True)
results.sort(key=lambda x:x['source'])
(tmp/'RENDER_MANIFEST.json').write_text(json.dumps({'documents':results,'total_pages':sum(x['pages'] for x in results)},indent=2)+'\n')
print('RENDERED',len(results),'documents;',sum(x['pages'] for x in results),'pages',flush=True)
