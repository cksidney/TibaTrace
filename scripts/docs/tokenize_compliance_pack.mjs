import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const root=path.resolve(process.argv[2]||'.');
const runtime=process.env.CODEX_WORKSPACE_NODE_MODULES;
if(!runtime)throw new Error('Set CODEX_WORKSPACE_NODE_MODULES to the bundled runtime package directory.');
const {marked}=await import(pathToFileURL(path.join(runtime,'marked/lib/marked.esm.js')));
const docs=[];
for(const group of ['system','dha']){
 const folder=path.join(root,'docs/compliance',group);
 for(const name of fs.readdirSync(folder).filter(n=>n.endsWith('.md')).sort()){
  const file=path.join(folder,name);
  const source=fs.readFileSync(file,'utf8').replace(/<!-- TIBATRACE DOCUMENT BRANDING START -->[\s\S]*?<!-- TIBATRACE DOCUMENT BRANDING END -->\s*/g,'');
  docs.push({group,name,sourcePath:path.relative(root,file),tokens:marked.lexer(source,{gfm:true})});
 }
}
const out=path.join(root,'tmp/document-branding/tokens.json');
fs.writeFileSync(out,JSON.stringify(docs,null,2));
console.log(`Tokenized ${docs.length} compliance documents.`);
