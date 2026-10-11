import test from 'node:test';
import assert from 'node:assert/strict';
import {parametersRequest,parameterPath,seedDecimal,safeFields,removeUnsupported,fieldDefaults} from '../frontend/src/pages/parameters/parametersClient.js';

test('uint64 seed decimal accepts max and rejects overflow, number input, unsafe syntax',()=>{
 assert.equal(seedDecimal('18446744073709551615'),true);
 for(const v of ['18446744073709551616',18446744073709551615n,Number.MAX_SAFE_INTEGER,'-1','01','1.0','+1',''])assert.equal(seedDecimal(v),false);
});
test('request paths allow only explicit Phase08 routes and never arbitrary redirect',()=>{
 assert.equal(parameterPath('/api/presets?id=one'),'/api/presets?id=one');
 for(const u of ['https://evil.test/api/presets','//evil.test','/api/admin/users','/api/jobs','/api/presets/../admin/users','/api/presets?a=%0d%0aSet-Cookie','/api/models/abc/worker-image','/api/parameter-intents#foo'])assert.throws(()=>parameterPath(u));
});
test('mutation uses cookie and CSRF but never browser shared token',async()=>{
 let target,options;
 const fetchImpl=async(path,opts)=>{target=path;options=opts;return {ok:true,status:201,json:async()=>({id:'new'})};};
 const out=await parametersRequest('/api/presets',{method:'POST',csrfToken:'session-csrf',body:{name:'foo'},fetchImpl});
 assert.equal(out.id,'new');assert.equal(target,'/api/presets');assert.equal(options.credentials,'same-origin');assert.equal(options.cache,'no-store');assert.equal(options.headers['X-CSRF-Token'],'session-csrf');
 assert.equal('X-Internal-Token' in options.headers,false);assert.equal('Authorization' in options.headers,false);
});
test('reject backend mismatch with consistent safe user message',async()=>{
 await assert.rejects(()=>parametersRequest('/api/presets',{fetchImpl:async()=>({ok:false,status:409,json:async()=>({detail:{secret:'abc'}})})}),e=>e.status===409&&!e.message.includes('abc'));
});
test('schema-driven fields use only keys provided by server',()=>{
 const schema={fields:[{key:'steps',type:'integer',default:4},{key:'prompt',type:'text'},{key:'__evil',type:'text'}]};
 assert.deepEqual(safeFields(schema).map(f=>f.key),['steps','prompt']);
 assert.deepEqual(fieldDefaults(schema),{steps:4});
 assert.deepEqual(removeUnsupported({prompt:'latest',cfg:4,steps:6},schema),{prompt:'latest',steps:6});
});
test('client never generates seed with Math.random or Date.now',()=>{
 const src=String(seedDecimal)+String(parametersRequest);
 assert.equal(src.includes('Math.random'),false);assert.equal(src.includes('Date.now'),false);
});
