/** Phase09 cookie+CSRF only, no Worker token, never sends GPU jobs. */
import {messageForStatus} from '../../auth/api.js';
const ALLOWED=/^\/api\/v2\/(semantic-workflows(?:\/[A-Za-z0-9_-]{1,96}\/versions)?|semantic-workflow-versions\/[A-Za-z0-9_-]{1,96}(?:\/(?:draft|validate|compile-preview|publish))?|semantic-workflow-templates(?:\/(?:text2img|img2img|multi_ref|image2video|text2video))?)$/;
export async function workflowRequest(path,{method='GET',body,csrfToken,signal,fetchImpl=globalThis.fetch}={}){
 if(!ALLOWED.test(path)) throw Error('Endpoint not allowed');
 const headers={Accept:'application/json'};
 if(body!==undefined)headers['Content-Type']='application/json';
 if(csrfToken)headers['X-CSRF-Token']=csrfToken;
 const response=await fetchImpl(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store',signal});
 let payload=null;
 try{payload=await response.json()}catch{}
 if(!response.ok){const e=new Error(messageForStatus(response.status));e.status=response.status;e.field_path=typeof payload?.detail?.field_path==='string'?payload.detail.field_path:'';throw e;}
 return payload;
}
export function safePreview(values,schema){
 const fields=new Set(schema.map(x=>x.key));return Object.fromEntries(Object.entries(values).filter(([key])=>fields.has(key)));
}
