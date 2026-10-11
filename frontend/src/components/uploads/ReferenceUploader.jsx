import React,{useEffect,useRef,useState} from 'react';
import {mediaRequest,allowedRoles} from '../../pages/library/mediaClient.js';
/** Draft-only: does not submit a GPU Job or claim that role binding was persisted. */
export function ReferenceUploader({ownerClient,epoch,slots=[{key:'input.image_1',label:'مرجع',roles:['reference']}],onChange=()=>{}}){
 const [items,setItems]=useState([]),[message,setMessage]=useState('');const aborts=useRef(new Map());const previews=useRef(new Set());
 useEffect(()=>()=>{for(const c of aborts.current.values())c.abort();for(const u of previews.current)URL.revokeObjectURL(u);},[epoch]);
 const slotsSafe=slots.filter(s=>/^[A-Za-z0-9._-]{1,80}$/.test(s.key)&&Array.isArray(s.roles)&&s.roles.every(r=>allowedRoles.includes(r)));
 async function add(file,slot){
  if(!file)return;const id=crypto.randomUUID();const local=URL.createObjectURL(file);previews.current.add(local);
  const item={id,file,fileName:file.name,local,slot:slot.key,role:slot.roles[0],state:'uploading',asset_id:null};
  setItems(old=>[...old,item]);setMessage('');
  const controller=new AbortController();aborts.current.set(id,controller);
  const fd=new FormData();fd.append('file',file);
  try{
   // fetch does not reveal upload byte progress: never invent a percentage.
   const response=await mediaRequest(ownerClient,'/api/uploads',{method:'POST',body:fd,signal:controller.signal});
   setItems(old=>old.map(x=>x.id===id?{...x,state:'ready',asset_id:response.asset_id}:x));
  }catch(e){if(!controller.signal.aborted)setItems(old=>old.map(x=>x.id===id?{...x,state:'error',error:e.message}:x));}
  finally{aborts.current.delete(id)}
 }
 function remove(id){aborts.current.get(id)?.abort();setItems(old=>{const it=old.find(x=>x.id===id);if(it?.local){URL.revokeObjectURL(it.local);previews.current.delete(it.local)}return old.filter(x=>x.id!==id)});}
 function move(id,delta){setItems(old=>{const list=[...old],i=list.findIndex(x=>x.id===id),j=i+delta;if(i<0||j<0||j>=list.length)return old;[list[i],list[j]]=[list[j],list[i]];return list});}
 useEffect(()=>onChange(items.filter(x=>x.state==='ready').map((x,i)=>({asset_id:x.asset_id,slot_key:x.slot,role:x.role,position:i}))),[items,onChange]);
 return <section className="p06-upload" aria-label="تصاویر مرجع"><h2>تصاویر مرجع</h2><p>هر فایل به‌صورت خصوصی آپلود می‌شود؛ نقش‌ها فقط برای اسلات‌های مجاز Workflow فعال هستند. ثبت Job هنوز غیرفعال است.</p>
  {slotsSafe.map(slot=><div className="p06-drop" key={slot.key} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();void add(e.dataTransfer.files?.[0],slot)}}>
    <label htmlFor={'upload-'+slot.key}>{slot.label} — فایل تصویری را بکشید یا انتخاب کنید</label><input id={'upload-'+slot.key} type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={e=>{void add(e.target.files?.[0],slot);e.target.value=''}}/>
  </div>)}
  <ol className="p06-upload-list">{items.map((x,i)=><li key={x.id}><img src={x.local} alt="پیش‌نمایش محلی مرجع"/><div><strong dir="auto">{x.fileName}</strong><p role="status">{x.state==='uploading'?'در حال آپلود؛ مقدار بایت فعلاً قابل اندازه‌گیری نیست':x.state==='ready'?'تأیید و ذخیره خصوصی شد':x.state==='error'?x.error:'انتخاب شده'}</p>
   <label>نقش <select value={x.role} onChange={e=>setItems(old=>old.map(y=>y.id===x.id?{...y,role:e.target.value}:y))}>{(slotsSafe.find(s=>s.key===x.slot)?.roles||['reference']).map(r=><option key={r}>{r}</option>)}</select></label></div>
   <div className="p06-reorder"><button type="button" disabled={i===0} onClick={()=>move(x.id,-1)}>بالا</button><button type="button" disabled={i===items.length-1} onClick={()=>move(x.id,1)}>پایین</button>{x.state==='error'&&<button type="button" onClick={()=>{remove(x.id);const s=slotsSafe.find(v=>v.key===x.slot);if(s)void add(x.file,s)}}>تلاش دوباره</button>}<button type="button" onClick={()=>remove(x.id)}>حذف از فرم</button></div></li>)}</ol>
  {message&&<p role="alert">{message}</p>}
 </section>
}
