/** Optional JSX AST + component smoke test; needs Node + TypeScript (already used by the project). */
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
let ts;
try{ts=require('typescript')}catch(e){console.error('TypeScript is required for this optional JSX test');process.exit(2)}
const root=path.resolve(__dirname,'..');
const sourcePath=path.join(root,'frontend/src/pages/video/VideoPages.jsx');
const source=fs.readFileSync(sourcePath,'utf8');
const sf=ts.createSourceFile(sourcePath,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.JSX);
assert.equal(sf.parseDiagnostics.length,0,sf.parseDiagnostics.map(x=>x.messageText).join('\n'));
const compiled=ts.transpileModule(source,{fileName:sourcePath,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},reportDiagnostics:true});
assert.equal(compiled.diagnostics?.length,0,compiled.diagnostics?.map(d=>d.messageText).join('\n'));
const CharacterReplacementPage=()=>null;
const jsx=(type,props)=>({type,props:props||{}});
const stubs={
 'react':{__esModule:true,default:{},useState:()=>[null,()=>{}],useEffect:()=>{}},
 'react/jsx-runtime':{jsx,jsxs:jsx,Fragment:Symbol.for('react.fragment')},
 '../../auth/session.jsx':{useAuth:()=>({})},
 '../../layouts/Layouts.jsx':{AppLink:()=>null},
 './videoClient.mjs':{videoRequest:()=>{},videoBlob:()=>{}},
 './CharacterReplacementPage.jsx':{CharacterReplacementPage},
 './video.css':{},'./video-edit-methods.css':{}
};
const sandbox={exports:{},require:(name)=>{
 if(!(name in stubs)) throw Error('Unmocked import: '+name);return stubs[name];
}};
vm.runInNewContext(compiled.outputText,sandbox,{filename:sourcePath,timeout:3000});
for(const name of ['VideoCreatePage','VideoEditPage','PrivateVideoPlayer'])assert.equal(typeof sandbox.exports[name],'function',name);
const tree=sandbox.exports.VideoEditPage();
let editorCount=0,methodCount=0,headings=[];
function walk(n){
 if(Array.isArray(n)){for(const x of n)walk(x);return}
 if(n===null||n===undefined||typeof n==='boolean')return;
 if(typeof n==='string'||typeof n==='number'){headings.push(String(n));return}
 if(typeof n==='object'){
   if(n.type===CharacterReplacementPage)editorCount++;
   if(String(n.props?.className||'').split(/\s+/).includes('v-edit-method'))methodCount++;
   walk(n.props?.children);
 }
}
walk(tree);
assert.equal(editorCount,1,'SCAIL-2 editor must be directly rendered on /edit/video');
assert.equal(methodCount,3,'editor lists three methods (one enabled)');
assert(headings.some(x=>x.includes('جایگزینی شخصیت')));
console.log('PASS: JSX syntax + three existing exports + embedded SCAIL-2 + method selector');
