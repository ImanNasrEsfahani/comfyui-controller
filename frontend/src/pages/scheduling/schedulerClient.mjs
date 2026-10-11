// Fixed allowlist, cookie-only, no provider credentials or user-supplied URLs.
export async function schedulerRequest(path,{method='GET',body,csrfToken,signal,fetchImpl=globalThis.fetch}={}){
 const allowed=['/api/v2/scheduling/me/queue-summary','/api/v2/scheduling/me/usage',
  '/api/v2/scheduling/admin/infrastructure','/api/v2/scheduling/admin/allocations',
  '/api/v2/scheduling/admin/decisions','/api/v2/scheduling/admin/scale-intents'];
 if(!allowed.includes(path)||!['GET','POST'].includes(method)|| (method==='POST'&&path!==allowed[5]))throw Error('Unsupported scheduling route');
 const response=await fetchImpl(path,{credentials:'same-origin',cache:'no-store',signal,method,
  headers:{Accept:'application/json',...(body?{'Content-Type':'application/json'}:{}),...(csrfToken?{'X-CSRF-Token':csrfToken}:{})},
  ...(body?{body:JSON.stringify(body)}:{})});
 const json=await response.json().catch(()=>null);
 if(!response.ok){const e=Error(({401:'نشست منقضی شده است.',403:'شما مجوز این بخش را ندارید.',409:'وضعیت صف یا Provider اجازه این عملیات را نمی‌دهد.',422:'اطلاعات ارسالی نامعتبر است.',503:'Scheduler هنوز فعال نشده است.'})[response.status]||'خطای ارتباط با Scheduler.');e.status=response.status;throw e;}
 return json;
}
