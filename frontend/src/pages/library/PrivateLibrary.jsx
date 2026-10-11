import {PrivateVideoPlayer} from '../video/VideoPages.jsx';
import React,{useCallback,useEffect,useRef,useState} from 'react';
import {useAuth} from '../../auth/session.jsx';
import {AppLink} from '../../layouts/Layouts.jsx';
import {navigate} from '../../app/navigation.js';
import {assetFilters,mediaPath,mediaRequest,privateMediaBlob,roleSlot,stableIndex} from './mediaClient.js';
import {FullscreenViewer} from '../../components/media/FullscreenViewer.jsx';
import {ReferenceUploader} from '../../components/uploads/ReferenceUploader.jsx';
import './privateLibrary.css';
function filenameFor(asset){const ext=({'image/png':'png','image/jpeg':'jpg','image/webp':'webp','image/gif':'gif','video/mp4':'mp4','video/webm':'webm'})[asset?.mime_type]||'bin';return `media-${asset?.asset_id||'file'}.${ext}`;}
function formatted(t){if(!t)return 'نامشخص';const date=new Date(t);return isNaN(+date)?'نامشخص':date.toLocaleDateString('fa-IR')}

function Thumb({asset,client,epoch}){
 const [src,setSrc]=useState(null),[state,setState]=useState('waiting'),[visible,setVisible]=useState(false),ref=useRef(null);
 useEffect(()=>{
  if(typeof IntersectionObserver==='undefined'){setVisible(true);return;}
  const observer=new IntersectionObserver(items=>{if(items.some(x=>x.isIntersecting)){setVisible(true);observer.disconnect();}},{rootMargin:'150px'});
  if(ref.current)observer.observe(ref.current);return()=>observer.disconnect();
 },[]);
 useEffect(()=>{
  if(!visible)return;
  let active=true;let made=null;const ctrl=new AbortController();setSrc(null);setState('loading');
  privateMediaBlob(client,asset.asset_id,'thumbnail',ctrl.signal).then(blob=>{
   if(!active)return;const url=URL.createObjectURL(blob);made=url;client.registerObjectUrl(url);setSrc(url);setState('ready');
  }).catch(e=>{if(active&&!ctrl.signal.aborted)setState('unavailable')});
  return()=>{active=false;ctrl.abort();if(made)URL.revokeObjectURL(made)};
 },[client,asset.asset_id,epoch,visible]);
 return <span ref={ref} className="p06-thumb-container">{src?<img src={src} alt="بندانگشتی خصوصی" loading="lazy"/>:<span className="p06-thumb-empty">{state==='waiting'?'در انتظار نمایش':state==='loading'?'بارگذاری…':'بدون بندانگشتی'}</span>}</span>;
}

export function PrivateLibrary({focusId=null}){
 const {ownerClient,epoch,session}=useAuth();const [assets,setAssets]=useState([]),[cursor,setCursor]=useState(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const [kind,setKind]=useState(''),[view,setView]=useState(null),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 const [reuse,setReuse]=useState(null),[role,setRole]=useState('reference'),[slot,setSlot]=useState('input.image_1');
 const controller=useRef(null),openButton=useRef(null);
 const load=useCallback(async(next=null)=>{
  controller.current?.abort();const ctrl=new AbortController();controller.current=ctrl;setLoading(true);setError('');
  try{const data=await mediaRequest(ownerClient,assetFilters({kind,cursor:next}),{signal:ctrl.signal});if(ctrl.signal.aborted)return;
    setAssets(old=>next?[...old,...data.items.filter(x=>!old.some(y=>y.asset_id===x.asset_id))]:data.items);
    setCursor(data.next_cursor);}
  catch(e){if(!ctrl.signal.aborted)setError(e.message)}finally{if(!ctrl.signal.aborted)setLoading(false)}
 },[ownerClient,kind]);
 useEffect(()=>{setAssets([]);setCursor(null);void load();return()=>controller.current?.abort()},[load,epoch,session.user?.id]);
 useEffect(()=>{if(focusId&&assets.some(x=>x.asset_id===focusId))setView(focusId)},[focusId,assets]);
 const close=useCallback(()=>{setView(null);openButton.current?.focus?.()},[]);
 const move=useCallback(delta=>{setView(prev=>{const idx=stableIndex(assets,prev);return assets[(idx+delta+assets.length)%assets.length]?.asset_id||null})},[assets]);
 async function download(asset){if(!asset)return;setBusy(true);setError('');try{
   const blob=await privateMediaBlob(ownerClient,asset.asset_id,'download');const url=URL.createObjectURL(blob);
   const link=document.createElement('a');link.href=url;link.download=filenameFor(asset);link.click();URL.revokeObjectURL(url);
  }catch(e){setError(e.message)}finally{setBusy(false)}}
 async function use(asset){if(!asset)return;setBusy(true);setError('');try{
  const response=await mediaRequest(ownerClient,`${mediaPath(asset.asset_id,'reuse')}?${roleSlot(role,slot)}`,{method:'POST'});
  setReuse(response);setNotice('مرجع مجاز است. ایجاد Job جدید تا رفع Gate امنیتی فعال نمی‌شود.');
 }catch(e){setError(e.message)}finally{setBusy(false)}}
 async function remove(asset){if(!asset||!window.confirm('فقط نمایش این Asset از کتابخانه حذف شود؟ فایل اصلی R2 پاک نمی‌شود.'))return;
  setBusy(true);setError('');try{await mediaRequest(ownerClient,mediaPath(asset.asset_id),{method:'DELETE'});
   setAssets(a=>a.filter(x=>x.asset_id!==asset.asset_id));setView(null);setNotice('فایل از کتابخانه پنهان شد. داده Job دست‌نخورده است.');
  }catch(e){setError(e.message)}finally{setBusy(false)}}
 const selected=assets.find(x=>x.asset_id===view);
 return <section className="p06-library" dir="rtl"><div className="p06-top"><div><h1>کتابخانه خصوصی من</h1><p>فایل‌ها فقط با نشست معتبر دریافت می‌شوند. هیچ پیوند عمومی دائمی صادر نمی‌شود.</p></div><AppLink to="/create/image">ساخت تصویر</AppLink></div>
  <div className="p06-filters"><label>نمایش <select value={kind} onChange={e=>setKind(e.target.value)}><option value="">همه</option><option value="image">تصویر</option><option value="video">ویدئو</option><option value="input">ورودی</option><option value="output">خروجی</option></select></label>
   <button type="button" disabled={loading} onClick={()=>void load()}>تازه‌سازی</button></div>
  {loading&&<p role="status">در حال بارگذاری اطلاعات مالک حساب…</p>}
  {error&&<p className="p04-alert" role="alert">{error}<button type="button" onClick={()=>void load()}>تلاش مجدد</button></p>}
  {notice&&<p role="status" className="p06-notice">{notice}</p>}
  {!loading&&!error&&!assets.length&&<div className="p06-empty">هنوز رسانه‌ای ندارید. <AppLink to="/create/image">شروع کنید</AppLink></div>}
  <div className="p06-grid">{assets.map(a=><article key={a.asset_id} className="p06-card"><button ref={view===a.asset_id?openButton:null} type="button" className="p06-thumb" onClick={()=>{openButton.current=document.activeElement;setView(a.asset_id)}} aria-label="نمایش فایل خصوصی"><Thumb asset={a} client={ownerClient} epoch={epoch}/></button>
    <div className="p06-cardmeta"><strong>{a.kind==='input'?'تصویر ورودی':'خروجی'} · {a.mime_type?.split('/')[0]||'media'}</strong><small>{formatted(a.created_at)}</small></div>
    <div className="p06-card-actions"><AppLink to={`/library/${encodeURIComponent(a.asset_id)}`}>جزئیات</AppLink><button type="button" disabled={busy} onClick={()=>void download(a)}>دانلود</button><button type="button" disabled={busy} onClick={()=>void use(a)}>استفاده مجدد</button></div>
   </article>)}</div>
  {cursor&&<button type="button" disabled={loading} onClick={()=>void load(cursor)}>نمایش بیشتر</button>}
  {selected&&<FullscreenViewer assets={assets} id={view} onMove={move} onClose={close} onDownload={download} onReuse={use} ownerClient={ownerClient} epoch={epoch}/>}
  {reuse&&<aside className="p06-reuse" role="status"><strong>Draft مرجع</strong><p>Asset: <code dir="ltr">{reuse.asset_id}</code></p><p>Role: {reuse.role}, Slot: {reuse.slot_key}</p><p>ثبت Lineage نهایی فقط در زمان ایجاد Job و تأیید Backend مجاز خواهد شد.</p>
  <label>Role <select value={role} onChange={e=>setRole(e.target.value)}><option>reference</option><option>identity</option><option>clothing</option><option>pose</option><option>background</option></select></label><label>Slot <input value={slot} onChange={e=>setSlot(e.target.value)} dir="ltr"/></label><button type="button" disabled={busy} onClick={()=>void use(reuse)}>بررسی نقش جدید</button><button type="button" onClick={()=>setReuse(null)}>بستن</button></aside>}
 </section>
}

export function PrivateAssetDetail({id}){
 const {ownerClient,epoch}=useAuth(),[item,setItem]=useState(null),[state,setState]=useState('loading'),[error,setError]=useState(''),[viewer,setViewer]=useState(false);
 useEffect(()=>{let live=true;const ctrl=new AbortController();setState('loading');setItem(null);
  mediaRequest(ownerClient,mediaPath(id),{signal:ctrl.signal}).then(data=>{if(live){setItem(data);setState('ready')}}).catch(e=>{if(live){setError(e.message);setState('error')}});
  return()=>{live=false;ctrl.abort();setItem(null)};
 },[id,epoch,ownerClient]);
 const [note,setNote]=useState('');
 async function download(){try{
  const blob=await privateMediaBlob(ownerClient,id,'download');const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filenameFor(item);a.click();URL.revokeObjectURL(url);
 }catch(e){setNote(e.message)}}
 async function reuse(){try{const result=await mediaRequest(ownerClient,mediaPath(id,'reuse')+'?'+roleSlot(),{method:'POST'});setNote('مرجع مجاز است؛ ثبت Job جدید همچنان غیرفعال است. شناسه: '+result.asset_id)}catch(e){setNote(e.message)}}
 async function remove(){if(!window.confirm('فایل فقط از کتابخانه پنهان شود؟'))return;try{
  await mediaRequest(ownerClient,mediaPath(id),{method:'DELETE'});navigate('/library');
 }catch(e){setNote(e.message)}}
 return <section className="p06-library" dir="rtl"><AppLink to="/library">بازگشت به کتابخانه</AppLink><h1>جزئیات رسانه</h1>{state==='loading'&&<p role="status">در حال خواندن جزئیات خصوصی…</p>}{state==='error'&&<p role="alert">{error}</p>}
 {item&&<><div className="p06-detail">{item.mime_type?.startsWith('video/')&&<PrivateVideoPlayer assetId={id}/>}<strong>{item.kind==='output'?'خروجی':'ورودی'}</strong><p>نوع: {item.mime_type}</p><p>ابعاد: {item.width??'?'} × {item.height??'?'}</p><p>حجم: {item.size_bytes??'نامشخص'} بایت</p><p>ساخته شده: {formatted(item.created_at)}</p>
  {item.job_id&&<AppLink to={`/jobs/${encodeURIComponent(item.job_id)}`}>Job مبدأ</AppLink>}
  <details><summary>اطلاعات فنی و روابط</summary><pre dir="ltr">{JSON.stringify({variants:item.variants,references:item.references},null,2)}</pre></details>
  <button type="button" onClick={()=>setViewer(true)}>نمایش تمام‌صفحه</button><button type="button" onClick={()=>void download()}>دانلود اصلی</button><button type="button" onClick={()=>void reuse()}>استفاده به‌عنوان مرجع</button><button type="button" onClick={()=>void remove()}>حذف از کتابخانه</button>{note&&<p role="status">{note}</p>}</div>
  {viewer&&<FullscreenViewer id={id} assets={[item]} onMove={()=>{}} onClose={()=>setViewer(false)} onDownload={()=>void download()} onReuse={()=>void reuse()} ownerClient={ownerClient} epoch={epoch}/>}
 </>}
 </section>
}
export function ReferenceDraftPanel(){const {ownerClient,epoch}=useAuth();return <div className="p06-library"><h2>آپلود مرجع خصوصی</h2><ReferenceUploader ownerClient={ownerClient} epoch={epoch} onChange={()=>{}}/><p role="status">Generate در حالت چندکاربره تا پیاده‌سازی مالکیت اتمیک در Phase 03 مسدود است.</p></div>}
