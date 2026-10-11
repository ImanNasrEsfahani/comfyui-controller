import test from 'node:test';
import assert from 'node:assert/strict';
import {createOwnerClient} from '../frontend/src/ownerClient.js';

test('owner client sends cookie/CSRF but never admin token',async()=>{
 const sent=[];
 const client=createOwnerClient({fetchImpl:async (path,options)=>{
   sent.push({path,options});return path==='/api/auth/csrf'?{ok:true,json:async()=>({csrf_token:'csrf'})}:{ok:true,status:200};
 }});
 await client.request('/api/jobs/owned/cancel',{method:'POST'});
 assert.equal(sent.length,2);
 assert.equal(sent[1].options.credentials,'same-origin');
 assert.equal(sent[1].options.headers['X-CSRF-Token'],'csrf');
 assert.equal(sent[1].options.headers['X-Internal-Token'],undefined);
});
test('invalidation rejects request from previously authenticated account',async()=>{
 let complete;
 const client=createOwnerClient({fetchImpl:async url=>url==='/api/auth/session'?{ok:true,json:async()=>({user:{id:'A'}})}:new Promise(resolve=>complete=resolve)});
 await client.session();const pending=client.request('/api/jobs');client.clearPrivateState();complete({ok:true,status:200});
 await assert.rejects(pending,/Account changed/);
});
test('owner client blocks legacy provider controls',async()=>{
 const client=createOwnerClient({fetchImpl:async()=>{throw Error('fetch should never run');}});
 await assert.rejects(client.request('/api/salad/stop'),/allowlisted/);
});
test('owner client storage cleanup removes old draft keys without touching unrelated data',()=>{
 const values=new Map([['comfyui-controller:variables:wf','sensitive'],['my-preferences','safe']]);
 const old=globalThis.localStorage;
 globalThis.localStorage={get length(){return values.size;},key:i=>[...values.keys()][i],removeItem:k=>values.delete(k)};
 try{createOwnerClient().clearPrivateState();assert.equal(values.has('comfyui-controller:variables:wf'),false);assert.equal(values.get('my-preferences'),'safe');}
 finally{if(old===undefined)delete globalThis.localStorage;else globalThis.localStorage=old;}
});
