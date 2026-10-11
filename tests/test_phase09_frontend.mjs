import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'..');
const src=fs.readFileSync(path.join(root,'frontend/src/pages/workflows/workflowClient.js'),'utf8');
const mod=await import('data:text/javascript;base64,'+Buffer.from(src.replace(/^import \{messageForStatus\} from .*;$/m,"const messageForStatus=(n)=>({401:'Unauthorized',403:'Forbidden',422:'Invalid',503:'Unavailable'})[n]||'Error';")).toString('base64'));
const file=(name)=>fs.readFileSync(path.join(root,name),'utf8');
function fake(status=200,json={items:[]}){const calls=[];const fetchImpl=async(...args)=>{calls.push(args);return {ok:status>=200&&status<300,status,json:async()=>json}};return {fetchImpl,calls}}
test('Allowlisted endpoints only',async()=>{await assert.rejects(mod.workflowRequest('https://evil.example/'),/not allowed/);await assert.rejects(mod.workflowRequest('/api/worker/claim'),/not allowed/);await assert.rejects(mod.workflowRequest('/api/v2/semantic-workflow-versions/abc/execute'),/not allowed/)});
test('Safe GET cookie scope, no-store',async()=>{const f=fake();await mod.workflowRequest('/api/v2/semantic-workflows',{fetchImpl:f.fetchImpl});assert.equal(f.calls[0][1].credentials,'same-origin');assert.equal(f.calls[0][1].cache,'no-store');assert.equal(f.calls[0][1].method,'GET')});
test('POST CSRF and JSON',async()=>{const f=fake(201,{id:'v'});await mod.workflowRequest('/api/v2/semantic-workflows',{method:'POST',body:{title:'Test'},csrfToken:'csrf-fixture',fetchImpl:f.fetchImpl});assert.equal(f.calls[0][1].headers['X-CSRF-Token'],'csrf-fixture');assert.equal(f.calls[0][1].body,'{"title":"Test"}')});
test('No raw server detail exposed for 403',async()=>{const f=fake(403,{detail:'secret token'});await assert.rejects(mod.workflowRequest('/api/v2/semantic-workflows',{fetchImpl:f.fetchImpl}),e=>e.status===403&&!e.message.includes('secret'))});
test('Server field_path only on structured detail, never raw prompt',async()=>{const f=fake(422,{detail:{code:'invalid_field',field_path:'edges.0',message:'private prompt'}});await assert.rejects(mod.workflowRequest('/api/v2/semantic-workflows',{fetchImpl:f.fetchImpl}),e=>e.field_path==='edges.0'&&!e.message.includes('private'))});
test('Only available fields serialized in safePreview',()=>assert.deepEqual(mod.safePreview({a:1,worker_token:'secret'},[{key:'a'}]),{a:1}));
test('Create and versions routes installed',()=>{const s=file('frontend/src/app/router.jsx');assert.match(s,/WorkflowStudio/);assert.match(s,/WorkflowVersions/);assert.match(s,/route.path==='\/workflows\/new'/)});
test('ReturnTo restricted to user route with ID',()=>{const s=file('frontend/src/auth/routeUtils.js');assert.match(s,/workflows\\\/\[A-Za-z0-9_-/);assert.match(s,/workflows\/new/)});
test('No browser internal Worker/GPU call in studio',()=>{const s=file('frontend/src/pages/workflows/WorkflowPages.jsx');assert.doesNotMatch(s,/\/api\/worker\/|\/api\/generation\/jobs/);assert.match(s,/compile-preview/)});
test('Source syntax all modified files',()=>{const ts=requireTs();for(const p of ['frontend/src/app/router.jsx','frontend/src/auth/routeUtils.js','frontend/src/layouts/Layouts.jsx','frontend/src/pages/workflows/workflowClient.js','frontend/src/pages/workflows/WorkflowPages.jsx']){const src=file(p),sf=ts.createSourceFile(p,src,ts.ScriptTarget.Latest,true,p.endsWith('.jsx')?ts.ScriptKind.JSX:ts.ScriptKind.JS);assert.equal(sf.parseDiagnostics.length,0,p+': '+sf.parseDiagnostics.map(d=>d.messageText).join(';'))}});
function requireTs(){return (awaitRequire)()}
function awaitRequire(){return globalThis.__ts||=requireFromNode('typescript')}
function requireFromNode(name){const {createRequire}=process.getBuiltinModule('module');const r=createRequire(import.meta.url);try{return r('/opt/nvm/versions/node/v22.16.0/lib/node_modules/typescript/lib/typescript.js')}catch{return r(name)}}
