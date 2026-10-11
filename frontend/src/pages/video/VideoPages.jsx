import React,{useEffect,useState} from 'react';
import {useAuth} from '../../auth/session.jsx';
import {AppLink} from '../../layouts/Layouts.jsx';
import {videoRequest,videoBlob} from './videoClient.mjs';
import './video.css';

export function VideoCreatePage(){
 const {ownerClient,session,epoch,mutationToken}=useAuth();
 const [models,setModels]=useState([]),[model,setModel]=useState(''),[policy,setPolicy]=useState(null);
 const [loading,setLoading]=useState(true),[error,setError]=useState(''),[message,setMessage]=useState('');
 const [form,setForm]=useState({intent:'text2video',prompt:'',seconds:3,fps:16,width:512,height:512,
  codec:'h264',seed:'0',start_frame:'',end_frame:''});
 useEffect(()=>{const ctrl=new AbortController();setLoading(true);setModels([]);setModel('');setPolicy(null);
  videoRequest(ownerClient,'/api/v2/video/models',{signal:ctrl.signal}).then(data=>{if(!ctrl.signal.aborted)setModels(data.items||[]);})
   .catch(e=>{if(!ctrl.signal.aborted)setError(e.message);}).finally(()=>{if(!ctrl.signal.aborted)setLoading(false)});
  return()=>ctrl.abort();},[ownerClient,session.user?.id,epoch]);
 useEffect(()=>{setPolicy(null);if(!model)return;let active=true;const ctrl=new AbortController();
  videoRequest(ownerClient,`/api/v2/video/models/${model}/parameters`,{signal:ctrl.signal})
   .then(p=>{if(active){setPolicy(p);setForm(old=>({...old,
     intent:p.intents?.includes(old.intent)?old.intent:p.intents?.[0]||old.intent,
     seconds:Math.min(old.seconds,p.max_seconds||old.seconds),fps:p.fps?.[0]||old.fps,
     width:p.dimensions?.[0]?.[0]||old.width,height:p.dimensions?.[0]?.[1]||old.height,
     codec:p.codecs?.[0]||old.codec}))}}).catch(e=>{if(active)setError(e.message)});
  return()=>{active=false;ctrl.abort()};},[model,ownerClient,epoch]);
 const update=(key,val)=>setForm(old=>({...old,[key]:val}));
 async function validate(e){e.preventDefault();setError('');setMessage('');
  try{const csrf=await mutationToken();const result=await videoRequest(ownerClient,'/api/v2/video/validate',
   {method:'POST',csrfToken:csrf,body:{...form,start_frame:form.start_frame||null,end_frame:form.end_frame||null,model_version_id:model}});
   setMessage(result.valid?'اطلاعات معتبرند؛ اجرای GPU همچنان غیرفعال است.':'ورودی تأیید نشد.');
  }catch(e){setError(e.message)}
 }
 return <section className="v13-page" aria-label="ساخت ویدئو"><h1>ساخت ویدئو با هوش مصنوعی</h1>
  <p role="status">این صفحه برای اعتبارسنجی Draft است. تا ثبت تست واقعی مدل و Worker، دکمه Generate فعال نمی‌شود و هزینه GPU ایجاد نمی‌شود.</p>
  {loading&&<p>در حال بررسی مدل‌های مجاز…</p>}{error&&<p role="alert">{error}</p>}
  {!loading&&!models.length&&<div className="v13-empty" role="status">هیچ مدل ویدئویی با شواهد کافی سازگاری و Runtime در Registry آماده نشده است. <AppLink to="/tools">مدل‌ها</AppLink></div>}
  <form onSubmit={validate} className="v13-form">
   <label>مدل ویدئو<select value={model} onChange={e=>setModel(e.target.value)} required><option value="">مدل تأییدشده را انتخاب کنید</option>{models.map(m=><option value={m.id} key={m.id}>{m.name} · {m.revision} (Worker هنوز تأیید نشده)</option>)}</select></label>
   <label>حالت<select value={form.intent} onChange={e=>update('intent',e.target.value)}><option value="text2video">متن به ویدئو</option><option value="image2video">تصویر به ویدئو</option></select></label>
   <label>توضیح ویدئو<textarea rows="4" maxLength="2000" required value={form.prompt} onChange={e=>update('prompt',e.target.value)}/></label>
   {form.intent==='image2video'&&<label>شناسه تصویر شروع از کتابخانه خصوصی<input required value={form.start_frame} onChange={e=>update('start_frame',e.target.value)} pattern="[A-Za-z0-9_-]+" placeholder="Asset ID"/><small>این مرحله تصویر دیگری را بدون مجوز دریافت نمی‌کند.</small></label>}
   {policy&&<>
    <label>مدت‌زمان<select value={form.seconds} onChange={e=>update('seconds',Number(e.target.value))}>{Array.from({length:policy.max_seconds||0},(_,i)=>i+1).map(s=><option key={s} value={s}>{s} ثانیه</option>)}</select></label>
    <label>فریم‌برثانیه<select value={form.fps} onChange={e=>update('fps',Number(e.target.value))}>{policy.fps.map(n=><option key={n} value={n}>{n}</option>)}</select></label>
    <label>ابعاد<select value={`${form.width}x${form.height}`} onChange={e=>{const [w,h]=e.target.value.split('x').map(Number);setForm(old=>({...old,width:w,height:h}))}}>{policy.dimensions.map(([w,h])=><option key={`${w}x${h}`} value={`${w}x${h}`}>{w} × {h}</option>)}</select></label>
    <label>Codec<select value={form.codec} onChange={e=>update('codec',e.target.value)}>{policy.codecs.map(x=><option key={x}>{x}</option>)}</select></label>
    <label>Seed (رشته ده‌دهی)<input inputMode="numeric" pattern="(0|[1-9][0-9]*)" value={form.seed} onChange={e=>update('seed',e.target.value)}/></label>
   </>}
   <div className="v13-actions"><button type="submit" disabled={!policy}>اعتبارسنجی بدون اجرا</button><button disabled type="button" title="تا تأیید واقعی Worker و GPU غیرفعال است">Generate (غیرفعال)</button></div>
  </form>{message&&<p role="status">{message}</p>}
  <AppLink to="/library">مشاهده ویدئوها در کتابخانه شخصی</AppLink>
 </section>;
}
export function VideoEditPage(){return <section className="v13-page"><h1>ویرایش ویدئو</h1><p role="status">هیچ Workflow و Model ویدئو‌ادیت با Runtime تأییدشده در این نسخه عرضه نشده است. Trim یا Video-to-Video جعلی فعال نمی‌شود.</p><AppLink to="/library">مشاهده و دانلود اصل ویدئوهای خودم</AppLink></section>}

export function PrivateVideoPlayer({assetId}){
 const {ownerClient,epoch}=useAuth(),[src,setSrc]=useState(null),[poster,setPoster]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 useEffect(()=>{let live=true,urls=[];const ctrl=new AbortController();setLoading(true);setError('');setSrc(null);setPoster(null);
  Promise.allSettled([videoBlob(ownerClient,assetId,'proxy',ctrl.signal),videoBlob(ownerClient,assetId,'poster',ctrl.signal)])
   .then(async ([proxy,thumb])=>{
    if(!live)return;
    if(proxy.status==='fulfilled'){const u=URL.createObjectURL(proxy.value);urls.push(u);setSrc(u)}
    if(thumb.status==='fulfilled'){const u=URL.createObjectURL(thumb.value);urls.push(u);setPoster(u)}
    if(proxy.status==='rejected')setError('نسخه مرورگری ویدئو آماده نیست؛ اصل فایل را می‌توانید دانلود کنید.');
   }).finally(()=>{if(live)setLoading(false)});
  return()=>{live=false;ctrl.abort();urls.forEach(u=>URL.revokeObjectURL(u))};
 },[assetId,ownerClient,epoch]);
 async function download(){setError('');try{const blob=await videoBlob(ownerClient,assetId,'original');const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`video-${assetId}.bin`;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000)}catch(e){setError(e.message)}}
 return <section className="v13-player" aria-label="پخش خصوصی ویدئو">{loading&&<p role="status">در حال دریافت Proxy خصوصی…</p>}
  {src&&<video src={src} poster={poster||undefined} controls preload="metadata" playsInline aria-label="پخش ویدئو"/>}
  {error&&<p role="alert">{error}</p>}<button type="button" onClick={()=>void download()}>دانلود فایل اصلی</button></section>
}
