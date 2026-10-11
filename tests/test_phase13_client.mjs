import {test} from 'node:test';import assert from 'node:assert/strict';
import {videoPath,videoRequest,videoBlob} from '../frontend/src/pages/video/videoClient.mjs';
test('Private media endpoint accepts only opaque asset id',()=>{
 assert.equal(videoPath('a_ABC-0','poster'),'/api/v2/video/assets/a_ABC-0/poster');
 for(const id of ['../secret','abc/xyz','%2F','']) assert.throws(()=>videoPath(id));
 assert.throws(()=>videoPath('asset','upload'));
});
test('No arbitrary user-provided API URL',async()=>{
 await assert.rejects(()=>videoRequest(null,'https://attacker.test/api/v2/video/models'),/Unsafe video endpoint/);
 await assert.rejects(()=>videoRequest(null,'/api/v2/video/jobs'),/Unsafe video endpoint/);
});
test('Cookie-only validated request with CSRF and no keys',async()=>{
 const calls=[];const fetchImpl=async (path,opts)=>{calls.push([path,opts]);return {ok:true,json:async()=>({valid:true})}};
 const result=await videoRequest(null,'/api/v2/video/validate',{method:'POST',csrfToken:'csrf',body:{intent:'text2video'},fetchImpl});
 assert.equal(result.valid,true);assert.equal(calls[0][1].credentials,'same-origin');
 assert.equal(calls[0][1].headers['X-CSRF-Token'],'csrf');
 assert.equal(calls[0][1].cache,'no-store');
 assert.ok(!JSON.stringify(calls).includes('X-Internal-Token'));
});
test('Missing csrf user does not claim success',async()=>{
 const fetchImpl=async()=>({ok:false,status:403,json:async()=>({error:'no permission'})});
 await assert.rejects(()=>videoRequest(null,'/api/v2/video/validate',{method:'POST',fetchImpl}),x=>x.status===403);
});
test('Private video downloaded as authenticated blob',async()=>{
 const calls=[];const fetchImpl=async(url,opts)=>{calls.push([url,opts]);return {ok:true,blob:async()=>new Blob(['123456789'])}};
 assert.equal((await videoBlob(null,'A','original',null,fetchImpl)).size,9);
 assert.equal(calls[0][1].credentials,'same-origin');
});
test('No fake empty video success',async()=>{
 await assert.rejects(()=>videoBlob(null,'A','proxy',null,async()=>({ok:true,blob:async()=>new Blob([])})),/Empty media/);
});
