import test from 'node:test';import assert from 'node:assert/strict';
import {studioRequest} from '../frontend/src/pages/workflows/studioClient.js';
const ok={ok:true,status:200,json:async()=>({revision:2})};
test('Studio request sets cookies/no-store',async()=>{let call;await studioRequest('/api/v2/studio/versions/abc/draft',{method:'PATCH',body:{revision:1},csrfToken:'x',fetchImpl:async(p,opt)=>{call={p,opt};return ok}});assert.equal(call.opt.credentials,'same-origin');assert.equal(call.opt.cache,'no-store');assert.equal(call.opt.headers['X-CSRF-Token'],'x');});
test('Disallow arbitrary endpoint / traversal',async()=>{await assert.rejects(()=>studioRequest('/api/v2/admin/secret'));await assert.rejects(()=>studioRequest('/api/v2/studio/versions/../draft'));});
test('Conflict surfaces 409 with safe code',async()=>{await assert.rejects(()=>studioRequest('/api/v2/studio/versions/a/draft',{fetchImpl:async()=>({ok:false,status:409,json:async()=>({detail:{code:'stale_revision',current_revision:3}})})}),e=>e.status===409&&e.details.current_revision===3);});
