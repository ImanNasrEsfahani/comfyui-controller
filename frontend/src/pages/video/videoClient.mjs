// Owner-session only. Explicit endpoint allowlist; no arbitrary object URLs/keys.
export function videoPath(id,part='original'){
 if(!/^[A-Za-z0-9_-]{1,96}$/.test(id)||!['original','poster','proxy'].includes(part))throw Error('Invalid video resource');
 return `/api/v2/video/assets/${encodeURIComponent(id)}/${part}`;
}
export async function videoRequest(ownerClient,path,{method='GET',body,csrfToken,signal,fetchImpl=globalThis.fetch}={}){
 const allowed=path==='/api/v2/video/models'||path==='/api/v2/video/validate'||
  /^\/api\/v2\/video\/models\/[A-Za-z0-9_-]{1,96}\/parameters$/.test(path);
 if(!allowed||(method!=='GET'&&!(method==='POST'&&path.endsWith('/validate'))))throw Error('Unsafe video endpoint');
 const response=await fetchImpl(path,{method,signal,credentials:'same-origin',cache:'no-store',
  headers:{...(csrfToken?{'X-CSRF-Token':csrfToken}:{}),...(body?{'Content-Type':'application/json'}:{})},
  ...(body?{body:JSON.stringify(body)}:{})});
 if(!response.ok){const e=Error(({401:'نشست شما منقضی شده است.',403:'دسترسی مجاز نیست.',404:'اطلاعات پیدا نشد.',422:'پارامتر نامعتبر است.',503:'مدل ویدئویی تأییدشده برای اجرا وجود ندارد.'})[response.status]||`خطای درخواست (${response.status})`);e.status=response.status;throw e;}
 return response.json();
}
export async function videoBlob(ownerClient,id,part='original',signal,fetchImpl=globalThis.fetch){
 const r=await fetchImpl(videoPath(id,part),{signal,credentials:'same-origin',cache:'no-store'});
 if(!r.ok){const e=Error(`Video media HTTP ${r.status}`);e.status=r.status;throw e;}
 const blob=await r.blob();if(!blob.size)throw Error('Empty media');return blob;
}
