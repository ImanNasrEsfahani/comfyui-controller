import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createOwnerClient} from '../frontend/src/ownerClient.js';

test('owner client sends cookies and CSRF but never legacy admin token', async () => {
  const seen = [];
  const client = createOwnerClient({fetchImpl: async (path,options) => {
    seen.push({path,options});
    if (path === '/api/auth/csrf') return {ok:true,json:async()=>({csrf_token:'csrf-token'})};
    return {ok:true,status:200,json:async()=>({ok:true})};
  }});
  await client.request('/api/jobs/x/cancel',{method:'POST'});
  assert.equal(seen.length,2);
  assert.equal(seen[1].options.credentials,'same-origin');
  assert.equal(seen[1].options.headers['X-CSRF-Token'],'csrf-token');
  assert.equal(seen[1].options.headers['X-Internal-Token'],undefined);
});

test('cross-account session invalidates pending stale responses', async () => {
  let callback=()=>{};
  const client=createOwnerClient({fetchImpl: async (url) => {
    if (url==='/api/auth/session') return {ok:true,json:async()=>({user:{id:'A'}})};
    return new Promise(resolve=>{callback=()=>resolve({ok:true,status:200})});
  }});
  await client.session();
  const pending=client.request('/api/jobs');
  client.clearPrivateState();
  callback();
  await assert.rejects(pending,/Account changed/);
});

test('denies privileged/out-of-allowlist requests', async () => {
  const client=createOwnerClient({fetchImpl:async()=>{throw new Error('request unexpectedly sent')}});
  await assert.rejects(client.request('/api/salad/stop'),/allowlisted/);
});
