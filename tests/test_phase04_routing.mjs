import test from 'node:test';
import assert from 'node:assert/strict';
import {safeReturnTo, routeFor, isAdmin, maskedEmail} from '../frontend/src/auth/routeUtils.js';
import {authRequest,ApiError,messageForStatus} from '../frontend/src/auth/api.js';

test('route table maps the six auth routes and legacy redirects',()=>{
 for(const p of ['/login','/register','/verify-email','/forgot-password','/reset-password','/auth/2fa'])assert.equal(routeFor(p).scope,'public');
 assert.deepEqual(routeFor('/'),{scope:'redirect',to:'/dashboard'});
 assert.equal(routeFor('/jobs/abc-123').scope,'user');
 assert.equal(routeFor('/admin/infrastructure').scope,'admin');
 assert.equal(routeFor('/admin/worker-secret').scope,'missing');
});
test('returnTo strictly user-scoped and same-origin',()=>{
 const denied=['https://evil.com','//evil.com','/\\evil.com','/login','/admin','/admin/infrastructure','javascript:alert(1)','/\n/dashboard','/jobs/','/jobs/%2f'];
 for(const v of denied)assert.equal(safeReturnTo(v),'/dashboard',v);
 assert.equal(safeReturnTo('/jobs/a?filter=succeeded'),'/jobs/a?filter=succeeded');
 assert.equal(safeReturnTo('/create/image'),' /create/image'.trim());
 assert.equal(safeReturnTo('/jobs/a#token=sensitive'),'/jobs/a');
});
test('admin permission requires backend roles',()=>{
 assert.equal(isAdmin({roles:['user']}),false);
 assert.equal(isAdmin({roles:['admin']}),true);
 assert.equal(isAdmin({roles:['superadmin']}),true);
 assert.equal(isAdmin({roles:[]}),false);
});
test('masked email avoids displaying full local part',()=>{
 assert.equal(maskedEmail('example@domain.com'),'e***@domain.com');
});
test('auth fetch stays on allowed API endpoints and cookie-only',async()=>{
 let captured;
 const response=await authRequest('/login',{method:'POST',body:{email:'a@example.com',password:'secret'},fetchImpl:async(url,opts)=>{
   captured={url,opts};return {ok:true,status:200,json:async()=>({authenticated:true})};
 }});
 assert.equal(response.authenticated,true);
 assert.equal(captured.url,'/api/auth/login');
 assert.equal(captured.opts.credentials,'same-origin');
 assert.equal(captured.opts.cache,'no-store');
 assert.equal(captured.opts.headers['X-Internal-Token'],undefined);
 assert.equal(captured.opts.headers.Authorization,undefined);
 await assert.rejects(authRequest('/../admin',{fetchImpl:async()=>{throw Error('must not call');}}));
});
test('errors do not expose server-private messages',async()=>{
 await assert.rejects(authRequest('/login',{method:'POST',fetchImpl:async()=>({ok:false,status:401,json:async()=>({detail:'email exists'})})}),
   e=>e instanceof ApiError && e.status===401 && !e.message.includes('email exists'));
 assert.match(messageForStatus(429),/تعداد/);
});
