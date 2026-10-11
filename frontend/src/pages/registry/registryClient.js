/** Phase07 same-origin Cookie+CSRF client, no browser admin token and no arbitrary URL. */
const allowed=/^\/api\/(catalog\/models|models\/[A-Za-z0-9_-]{1,96}(?:\/capabilities)?|admin\/(models(?:\/families|\/[A-Za-z0-9_-]{1,96})?|model-artifacts|worker-images(?:\/[A-Za-z0-9_-]{1,96})?|gpu-profiles|deployment-variable-schema|deployment-profiles(?:\/[A-Za-z0-9_-]{1,96}(?:\/(?:history|revisions|validate|approve|activate|rollback))?)?|compatibility|registry-audit))(?:\?[a-zA-Z0-9_=&%-]*)?$/;
export function registryPath(path){if(typeof path!=='string'||!allowed.test(path))throw new Error('Registry API path not allowlisted');return path;}
export async function registryRequest(path,{method='GET',body,csrfToken,fetchImpl=globalThis.fetch,signal}={}){
 registryPath(path);method=method.toUpperCase();if(!['GET','POST','PATCH'].includes(method))throw new Error('Registry method not allowed');
 const headers={Accept:'application/json'};
 if(body!==undefined)headers['Content-Type']='application/json';if(csrfToken)headers['X-CSRF-Token']=csrfToken;
 const r=await fetchImpl(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin',cache:'no-store',signal});
 let value=null;try{value=await r.json()}catch{}
 if(!r.ok){let e=new Error(({401:'نشست معتبر نیست.',403:'مجوز مدیریتی وجود ندارد.',404:'مورد یافت نشد.',409:'تداخل نسخه.',422:'مقدار واردشده معتبر نیست.',503:'عملیات به تأیید Runtime/Staging نیاز دارد.'})[r.status]||'خطای سرویس Registry');e.status=r.status;throw e;}return value;
}
export function maskEnv(record,specs){return Object.fromEntries(Object.entries(record).map(([key,v])=>[key,specs.find(s=>s.key===key)?.secret?'[configured]':v]));}
