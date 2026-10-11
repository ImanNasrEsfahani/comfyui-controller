/** Phase10 restricted same-origin Studio routes. No public Worker token. */
import {messageForStatus} from '../../auth/api.js';
const PATH=/^\/api\/v2\/studio\/(?:nodes|versions\/[A-Za-z0-9_-]{1,96}\/(?:editor|draft|validate|publish|restore|compile-preview)|workflows\/[A-Za-z0-9_-]{1,96}\/unpublish)$/;
export async function studioRequest(path,{method='GET',body,csrfToken,signal,fetchImpl=globalThis.fetch}={}){
 if(!PATH.test(path))throw Error('Studio endpoint not allowed');
 const headers={Accept:'application/json'};if(body!==undefined)headers['Content-Type']='application/json';if(csrfToken)headers['X-CSRF-Token']=csrfToken;
 const response=await fetchImpl(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store',signal});
 let content={};try{content=await response.json()}catch{}
 if(!response.ok){const error=new Error(typeof content?.detail==='string'?content.detail:content?.detail?.code==='stale_revision'?'ویرایش دیگری ذخیره شده است؛ تغییرات شما حفظ شده‌اند.':messageForStatus(response.status));error.status=response.status;error.details=content?.detail;throw error;}
 return content;
}
