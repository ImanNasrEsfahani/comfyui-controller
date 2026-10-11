import test from 'node:test';import assert from 'node:assert/strict';
import {schedulerRequest} from '../frontend/src/pages/scheduling/schedulerClient.mjs';
test('Reject non-allowlisted provider endpoint',async()=>{
 await assert.rejects(schedulerRequest('/api/salad/start',{fetchImpl:()=>{throw Error('called')}}),/Unsupported/);
});
test('GET uses browser scoped credentials and no-store',async()=>{
 let o;
 const result=await schedulerRequest('/api/v2/scheduling/me/usage',{fetchImpl:async(p,opts)=>{o={p,opts};return {ok:true,json:async()=>({allocated_seconds_estimate:0})}}});
 assert.equal(o.p,'/api/v2/scheduling/me/usage');assert.equal(o.opts.credentials,'same-origin');assert.equal(o.opts.cache,'no-store');
 assert.equal(result.allocated_seconds_estimate,0);
});
test('Scale request keeps CSRF and preview acknowledgement',async()=>{
 let sent;
 await schedulerRequest('/api/v2/scheduling/admin/scale-intents',{method:'POST',csrfToken:'test-csrf',
 body:{revision_id:'rev-1',action:'hold',acknowledge_non_executing_preview:true,reason_code:'manual_review'},
 fetchImpl:async(_p,opt)=>{sent=opt;return {ok:true,json:async()=>({state:'requested',submitted_to_provider:false})}}});
 assert.equal(sent.headers['X-CSRF-Token'],'test-csrf');assert.equal(JSON.parse(sent.body).acknowledge_non_executing_preview,true);
});
test('Denies arbitrary post path',async()=>{
 await assert.rejects(schedulerRequest('/api/v2/scheduling/admin/infrastructure',{method:'POST'}),/Unsupported/);
});
test('Maps 401/403/409/422/503 safely',async()=>{
 for(const code of [401,403,409,422,503]){
  await assert.rejects(schedulerRequest('/api/v2/scheduling/me/usage',{fetchImpl:async()=>({ok:false,status:code,json:async()=>({detail:'SECRET'})})}),e=>e.status===code&&!e.message.includes('SECRET'));
 }
});
test('No cache or secret parameters in URL for private read',async()=>{
 await assert.rejects(schedulerRequest('/api/v2/scheduling/me/usage?user_id=B'),/Unsupported/);
});
