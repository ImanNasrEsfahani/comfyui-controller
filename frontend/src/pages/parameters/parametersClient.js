/** Same-origin, cookie-only, deny-by-default Phase08 browser API. */
const allowed=/^\/api\/(?:catalog\/models|models\/[A-Za-z0-9_-]{1,96}\/(?:parameter-schemas|parameter-schema|loras)|presets(?:\/[A-Za-z0-9_-]{1,96}(?:\/preview)?)?|parameter-intents(?:\/[A-Za-z0-9_-]{1,96})?|admin\/(?:loras|parameter-schemas(?:\/[A-Za-z0-9_-]{1,96}\/publish)?))(?:\?[A-Za-z0-9_=&%.-]*)?$/;
export function parameterPath(path){if(typeof path!=='string'||(!allowed.test(path)||/%0[ad]|%7f|%25/i.test(path)))throw Error('Unapproved parameter API path');return path;}
export function seedDecimal(value){return typeof value==='string' && /^(0|[1-9]\d{0,19})$/.test(value) && BigInt(value)<=(1n<<64n)-1n;}
export function safeFields(schema){return Array.isArray(schema?.fields)?schema.fields.filter(f=>typeof f.key==='string'&&/^[A-Za-z][A-Za-z0-9_.-]{0,79}$/.test(f.key)):[];}
export function fieldDefaults(schema){return Object.fromEntries(safeFields(schema).filter(f=>Object.hasOwn(f,'default')).map(f=>[f.key,f.default]));}
export function removeUnsupported(form,schema){const keys=new Set(safeFields(schema).map(f=>f.key));return Object.fromEntries(Object.entries(form).filter(([k])=>keys.has(k)));}
export async function parametersRequest(path,{method='GET',body,csrfToken,signal,fetchImpl=globalThis.fetch}={}){
 parameterPath(path);method=method.toUpperCase();if(!['GET','POST','PATCH','DELETE'].includes(method))throw Error('Unsupported method');
 const headers={Accept:'application/json'};if(body!==undefined)headers['Content-Type']='application/json';if(csrfToken)headers['X-CSRF-Token']=csrfToken;
 const response=await fetchImpl(path,{method,headers,credentials:'same-origin',cache:'no-store',signal,...(body!==undefined?{body:JSON.stringify(body)}:{})});
 let data=null;try{data=await response.json()}catch{}
 if(!response.ok){const error=new Error(({401:'نشست معتبر نیست.',403:'مجوز کافی نیست.',404:'مدل یا Preset پیدا نشد.',409:'نسخه مدل یا Workflow با تنظیمات فعلی ناسازگار است.',422:'یک یا چند پارامتر نامعتبر است.',503:'این قابلیت روی سرور فعال نیست.'})[response.status]||'خطای ارتباط');error.status=response.status;error.fieldPath=data?.detail?.field_path;throw error;}
 return data;
}
