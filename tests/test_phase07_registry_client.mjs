import test from 'node:test';
import assert from 'node:assert/strict';
import {registryRequest,registryPath,maskEnv} from '../frontend/src/pages/registry/registryClient.js';
test('strict route allowlist and query rejects redirects',()=>{
 for(const path of ['https://evil.invalid/api/admin/models','//evil.invalid/api/admin/models','/api/admin/models/abc/execute','/api/admin/models?q=<script>'])assert.throws(()=>registryPath(path));
 for(const path of ['/api/catalog/models','/api/admin/models','/api/admin/worker-images','/api/admin/gpu-profiles','/api/admin/deployment-profiles','/api/admin/deployment-profiles/a/validate?revision_id=b'])assert.equal(registryPath(path),path);
});
test('Cookie no-store and no internal worker/admin token',async()=>{
 let output;let result=await registryRequest('/api/admin/models',{fetchImpl:async(path,opts)=>{output=opts;return {ok:true,json:async()=>({items:[]})}}});
 assert.deepEqual(result,{items:[]});assert.equal(output.credentials,'same-origin');assert.equal(output.cache,'no-store');assert.ok(!JSON.stringify(output).includes('X-Internal-Token'));
});
test('CSRF mutation and body remain JSON',async()=>{
 let observed;await registryRequest('/api/admin/models/families',{method:'POST',body:{name:'A'},csrfToken:'fake-test',fetchImpl:async(_,opts)=>{observed=opts;return {ok:true,json:async()=>({id:'x'})}}});
 assert.equal(observed.headers['X-CSRF-Token'],'fake-test');assert.equal(JSON.parse(observed.body).name,'A');
});
test('HTTP status errors never render raw error payload',async()=>{
 for(const status of [401,403,409,422,503])await assert.rejects(()=>registryRequest('/api/admin/models',{fetchImpl:async()=>({ok:false,status,json:async()=>({error:{token:'never_print_me'}})})}),e=>e.status===status&&!e.message.includes('never_print_me'));
});
test('reject DELETE for immutable registry',async()=>{await assert.rejects(()=>registryRequest('/api/admin/models',{method:'DELETE',fetchImpl:()=>{throw Error('should not call')}}),/method not allowed/i)});
test('UI helper mask env placeholders',()=>{assert.deepEqual(maskEnv({R2_ACCESS_KEY_REF:'vault://hidden',LOG_LEVEL:'INFO'},[{key:'R2_ACCESS_KEY_REF',secret:1}]),{R2_ACCESS_KEY_REF:'[configured]',LOG_LEVEL:'INFO'});});
