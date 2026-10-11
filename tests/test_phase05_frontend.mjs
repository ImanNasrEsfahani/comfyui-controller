import {test} from 'node:test';
import assert from 'node:assert/strict';
import {routeFor,isAdmin,safeReturnTo} from '../frontend/src/auth/routeUtils.js';
import {accountRequest} from '../frontend/src/pages/accountClient.js';

test('new user/account/admin paths have exact scope and safe deep links',()=>{
 for(const p of ['/dashboard','/account/profile','/account/preferences','/account/data']){
   assert.equal(routeFor(p).scope,'user');assert.equal(safeReturnTo(p),p);
 }
 for(const p of ['/admin','/admin/users','/admin/users/user-123','/admin/audit-logs'])assert.equal(routeFor(p).scope,'admin');
 assert.equal(safeReturnTo('//evil.com'),'/dashboard');
 assert.equal(isAdmin({roles:['user']}),false);
 assert.equal(isAdmin({roles:['superadmin']}),true);
});

test('account request is strictly cookie-based, no admin/worker token',async()=>{
 const calls=[];
 const res=await accountRequest('/api/users/me/preferences',{method:'PATCH',body:{theme:'dark'},csrfToken:'csrf-from-server',fetchImpl:async(url,opt)=>{calls.push({url,opt});return {ok:true,status:200,json:async()=>({theme:'dark'})};}});
 assert.equal(res.theme,'dark');assert.equal(calls[0].opt.credentials,'same-origin');
 assert.equal(calls[0].opt.cache,'no-store');assert.equal(calls[0].opt.headers['X-CSRF-Token'],'csrf-from-server');
 assert.equal('X-Internal-Token' in calls[0].opt.headers,false);
 await assert.rejects(()=>accountRequest('/api/salad/settings'));
 await assert.rejects(()=>accountRequest('//evil.example/api/users/me'));
});

test('403 and 503 become user-safe errors without credential echo',async()=>{
 for(const status of [403,503]){
  await assert.rejects(()=>accountRequest('/api/admin/users',{fetchImpl:async()=>({ok:false,status,json:async()=>({detail:'SECRET_TOKEN'})})}),e=>{
   assert.equal(e.status,status);assert.equal(e.message.includes('SECRET_TOKEN'),false);return true;
  });
 }
});
