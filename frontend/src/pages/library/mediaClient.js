/** Phase06 private media transport. URLs never carry storage keys or signer secrets. */
export const allowedRoles=Object.freeze(['identity','clothing','pose','background','mask','reference','start_frame','end_frame']);
export function mediaPath(id,part='') {
  if (!/^[A-Za-z0-9_-]{1,96}$/.test(String(id))) throw new Error('Invalid asset identifier');
  return `/api/assets/${encodeURIComponent(id)}${part?'/'+part:''}`;
}
export function assetFilters({kind='',status='',after='',before='',model='',project='',cursor=''}={}) {
  const q=new URLSearchParams({limit:'24'});
  for(const [key,value] of Object.entries({type:kind,status,after,before,model,project,cursor}))if(value)q.set(key,String(value));
  return `/api/assets?${q}`;
}
export function roleSlot(role='reference',slot='input.image_1') {
  if(!allowedRoles.includes(role)||!/^[A-Za-z0-9._-]{1,80}$/.test(slot))throw new Error('Invalid reference binding');
  return new URLSearchParams({role,slot}).toString();
}
export async function mediaRequest(ownerClient,path,options={}) {
  const r=await ownerClient.request(path,options);
  if (!r.ok) {
    const error=new Error(({401:'نشست منقضی شده است.',403:'دسترسی مجاز نیست.',404:'فایل یافت نشد یا مجوز ندارید.',409:'این فایل به کار دیگری وابسته است.',413:'فایل بیش از اندازه مجاز است.',422:'فرمت یا اطلاعات نامعتبر است.',429:'لطفاً کمی بعد تلاش کنید.',503:'این قابلیت در سرور آماده نیست.'})[r.status]||`خطای درخواست (${r.status})`);
    error.status=r.status;throw error;
  }
  if (r.status===204)return null;
  return r.json();
}
export async function privateMediaBlob(ownerClient,id,part='preview',signal) {
  if(!['preview','thumbnail','download'].includes(part))throw new Error('Invalid media action');
  const r=await ownerClient.request(mediaPath(id,part),{signal});
  if(!r.ok){const e=new Error(`Media HTTP ${r.status}`);e.status=r.status;throw e;}
  const blob=await r.blob();if(!blob.size)throw new Error('Empty media body');return blob;
}
export function stableIndex(list,id) {return Math.max(0,list.findIndex(a=>a.asset_id===id));}
