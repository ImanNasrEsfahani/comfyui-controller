import test from 'node:test';
import assert from 'node:assert/strict';
import {mediaPath,assetFilters,roleSlot,allowedRoles,privateMediaBlob,mediaRequest} from '../frontend/src/pages/library/mediaClient.js';
import {createOwnerClient} from '../frontend/src/ownerClient.js';
test('Media URL is ID only (no original key or arbitrary path)',()=>{
 assert.equal(mediaPath('A_12','thumbnail'),'/api/assets/A_12/thumbnail');
 assert.throws(()=>mediaPath('../private'),/Invalid asset identifier/);
 assert.equal(assetFilters({kind:'image',cursor:'opaque'}).includes('type=image'),true);
});
test('Only recognized reference roles and slots',()=>{
 assert.ok(allowedRoles.includes('pose'));
 assert.ok(roleSlot('identity','input.image_1').includes('identity'));
 assert.throws(()=>roleSlot('admin','input.image_1'));
 assert.throws(()=>roleSlot('pose','../secret'));
});
test('Owner client sends cookie and CSRF but never admin token',async()=>{
 const seen=[];
 const fetchImpl=async (path,opts)=>{seen.push({path,opts});if(path==='/api/auth/csrf')return {ok:true,json:async()=>({csrf_token:'csrf-unit-test'})};return {ok:true,status:200,json:async()=>({asset_id:'a'})}};
 const c=createOwnerClient({fetchImpl});await mediaRequest(c,'/api/assets/a/reuse?role=pose&slot=input.image_1',{method:'POST'});
 assert.equal(seen[1].opts.headers['X-CSRF-Token'],'csrf-unit-test');
 assert.equal(seen[1].opts.credentials,'same-origin');
 assert.ok(!('X-Internal-Token' in seen[1].opts.headers));
});
test('Preview response uses owner cookie; rejects 404 without signed fallback',async()=>{
 const data=new Uint8Array([137,80,78,71]);
 const fake={request:async(path,opts)=>({ok:true,blob:async()=>new Blob([data])})};
 const blob=await privateMediaBlob(fake,'A_1');assert.equal(blob.size,4);
 await assert.rejects(()=>privateMediaBlob({request:async()=>({ok:false,status:404})},'A_1'),/404/);
});
test('An unauthenticated session loses media requests',async()=>{
 let lost=0;
 const c=createOwnerClient({fetchImpl:async()=>({ok:false,status:401}),onAuthLost:()=>lost++});
 const res=await c.request('/api/assets');assert.equal(res.status,401);assert.equal(lost,1);
});
