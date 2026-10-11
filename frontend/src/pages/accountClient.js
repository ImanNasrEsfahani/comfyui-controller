/** Phase05 cookie-only account client. No token persistence, no arbitrary URLs. */
export async function accountRequest(path, {method='GET', body, csrfToken, signal, fetchImpl=globalThis.fetch}={}) {
  if (typeof path!=='string' || !/^\/api\/(users\/me(?:\/preferences|\/email-change|\/verify-email-change)?|dashboard\/summary|account\/(activity|data-summary|export-request|delete-request)|admin\/(summary|users(?:\/[A-Za-z0-9_-]+(?:\/role)?)?|audit-logs))(?:\?[^#]*)?$/.test(path)) {
    throw new Error('Account API path is not allowlisted');
  }
  const m=method.toUpperCase();
  if(!['GET','PATCH','POST'].includes(m))throw new Error('Method not allowed by account client');
  const headers={Accept:'application/json'};
  if(body!==undefined)headers['Content-Type']='application/json';
  if(csrfToken)headers['X-CSRF-Token']=csrfToken;
  const r=await fetchImpl(path,{method:m,headers,credentials:'same-origin',cache:'no-store',signal,
    ...(body!==undefined?{body:JSON.stringify(body)}:{})});
  let data=null;
  if(r.status!==204){try{data=await r.json();}catch{data=null;}}
  if(!r.ok){const e=new Error(({401:'نشست منقضی شد؛ دوباره وارد شوید.',403:'مجوز دسترسی ندارید.',404:'اطلاعات پیدا نشد.',409:'این عملیات با وضعیت حساب سازگار نیست.',422:'اطلاعات واردشده را بررسی کنید.',429:'لطفاً بعداً دوباره تلاش کنید.',503:'این قابلیت هنوز فعال نشده است.'})[r.status]||'خطای سرویس؛ دوباره تلاش کنید.');e.status=r.status;throw e;}
  return data;
}
