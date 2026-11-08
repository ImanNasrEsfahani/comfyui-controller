import React,{useCallback,useEffect,useRef,useState} from 'react';
import {useAuth} from '../../auth/session.jsx';
import {AppLink} from '../../layouts/Layouts.jsx';
import './character-replacement.css';

const ROOT='/api/v2/character-replace';
const ACTIVE=new Set(['queued','preparing','running','uploading','cancel_requested']);
const LABELS={queued:'در صف',preparing:'در حال آماده‌سازی',running:'پردازش ویدئو',uploading:'ذخیره نتیجه',
  cancel_requested:'در حال لغو',succeeded:'آماده',failed:'ناموفق',stalled:'ارتباط Worker قطع شده',cancelled:'لغو شده'};
const DEFAULTS={prompt:'',detect_prompt:'a person',quality:'quality',steps:24,seed:'1',preserve_audio:true,confirmed_rights:false};

async function request(path,{method='GET',body,csrf,signal}={}){
 const headers={Accept:'application/json'};
 if(csrf)headers['X-CSRF-Token']=csrf;
 if(body!==undefined && !(body instanceof FormData))headers['Content-Type']='application/json';
 const response=await fetch(ROOT+path,{method,credentials:'same-origin',cache:'no-store',headers,signal,
   ...(body===undefined?{}:{body:body instanceof FormData?body:JSON.stringify(body)})});
 let data=null;
 if(response.status!==204)try{data=await response.json();}catch{}
 if(!response.ok)throw new Error(typeof data?.detail==='string'?data.detail:`خطای HTTP ${response.status}`);
 return data;
}

function UploadCard({label,kind,file,onFile,meta,loading,onUpload}){
 const accept=kind==='video'?'video/mp4,video/webm':'image/jpeg,image/png,image/webp';
 return <div className="cr-upload"><label className="cr-heading">{label}</label>
  <label className="cr-filebox"><span aria-hidden="true">{kind==='video'?'▣':'▧'}</span>
   <strong>{file?.name || 'فایل را انتخاب کنید'}</strong>
   <small>{kind==='video'?'MP4 / WebM — حداکثر ۱۰ ثانیه و ۹۰ مگابایت':'PNG / JPG / WebP — چهره و بدن واضح'}</small>
   <input type="file" accept={accept} onChange={e=>onFile(e.target.files?.[0]||null)} aria-label={label}/></label>
  {kind==='video'&&file&&<p className="cr-hint">ویدئوی اصلی باید یک شخص هدف واضح داشته باشد.</p>}
  <div className="cr-inline"><button type="button" disabled={!file||loading} onClick={onUpload}>
    {loading?'در حال انتقال…':meta?'جایگزینی فایل':'آپلود فایل'}</button>
   {meta&&<span className="cr-ok">✓ آماده · {meta.width} × {meta.height}</span>}</div>
 </div>
}

export function CharacterReplacementPage(){
 const {mutationToken,session,epoch}=useAuth();
 const [config,setConfig]=useState(null),[configError,setConfigError]=useState('');
 const [form,setForm]=useState(DEFAULTS),[files,setFiles]=useState({video:null,reference:null});
 const [assets,setAssets]=useState({video:null,reference:null});
 const [uploading,setUploading]=useState(''),[submitting,setSubmitting]=useState(false);
 const [jobs,setJobs]=useState([]),[error,setError]=useState(''),[success,setSuccess]=useState('');
 const keyRef=useRef(null),urls=useRef([]),uploadVersions=useRef({video:0,reference:0});
 const [preview,setPreview]=useState({video:null,reference:null});
 useEffect(()=>{return()=>urls.current.forEach(url=>URL.revokeObjectURL(url));},[]);
 const refresh=useCallback(async()=>{
  try{const data=await request('/jobs');setJobs(data.items||[]);}catch(e){setError(e.message)}
 },[]);
 useEffect(()=>{let active=true;const controller=new AbortController();
  request('/config',{signal:controller.signal}).then(data=>{if(active)setConfig(data)}).catch(e=>{if(active)setConfigError(e.message)});
  refresh();return()=>{active=false;controller.abort()};
 },[epoch,session.user?.id,refresh]);
 useEffect(()=>{if(!jobs.some(item=>ACTIVE.has(item.state)))return;
  const id=setInterval(()=>{void refresh()},5000);return()=>clearInterval(id);
 },[jobs,refresh]);
 function update(k,value){setForm(v=>({...v,[k]:value}));keyRef.current=null}
 function chooseFile(kind,file){
  if(preview[kind]){URL.revokeObjectURL(preview[kind]);urls.current=urls.current.filter(x=>x!==preview[kind]);}
  let url=file?URL.createObjectURL(file):null;if(url)urls.current.push(url);
  uploadVersions.current[kind]+=1;
  setPreview(v=>({...v,[kind]:url}));setFiles(v=>({...v,[kind]:file}));
  setAssets(v=>({...v,[kind]:null}));setError('');keyRef.current=null;
 }
 async function upload(kind){const file=files[kind];if(!file)return;
  const version=uploadVersions.current[kind];
  setUploading(kind);setError('');setSuccess('');
  try{const csrf=await mutationToken(),body=new FormData();body.append('file',file);
   const response=await request('/assets/'+kind,{method:'POST',body,csrf});
   if(version===uploadVersions.current[kind]){
    setAssets(v=>({...v,[kind]:response}));setSuccess('فایل با موفقیت در فضای خصوصی ذخیره شد.');
   }
  }catch(e){setError(e.message)}finally{setUploading('')}
 }
 async function submit(e){e.preventDefault();if(!assets.video||!assets.reference||submitting)return;
  setSubmitting(true);setError('');setSuccess('');
  try{const csrf=await mutationToken();if(!keyRef.current)keyRef.current=crypto.randomUUID();
   const response=await request('/jobs',{method:'POST',csrf,body:{...form,source_video_id:assets.video.asset_id,
       reference_image_id:assets.reference.asset_id,client_request_id:keyRef.current}});
   setSuccess('Job ثبت شد: '+response.id+' · نتیجه در فهرست کارها نمایش داده می‌شود.');
   await refresh();keyRef.current=null;
  }catch(e){setError(e.message)}finally{setSubmitting(false)}
 }
 async function action(job,verb){setError('');try{const csrf=await mutationToken();
  await request(`/jobs/${job.id}/${verb}`,{method:'POST',csrf});await refresh();
 }catch(e){setError(e.message)}}
 async function download(job){try{const response=await fetch(`${ROOT}/jobs/${job.id}/result`,{credentials:'same-origin',cache:'no-store'});
  if(!response.ok)throw new Error('فایل خروجی در دسترس نیست');const blob=await response.blob();
  const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`scail2-${job.id}.mp4`;a.click();
  setTimeout(()=>URL.revokeObjectURL(url),10000);
 }catch(e){setError(e.message)}}
 const canSubmit=Boolean(config&&assets.video&&assets.reference&&form.confirmed_rights&&!submitting);
 return <section className="cr-page" aria-label="ویرایش کاراکتر در ویدئو">
  <header className="cr-title"><div><span className="cr-eyebrow">AI VIDEO STUDIO / SCAIL-2</span>
   <h1>جایگزینی شخصیت در ویدئو</h1><p>شخصیت جدید را با حرکت و پس‌زمینه ویدئوی اصلی ترکیب کنید.</p></div>
   <span className="cr-model">SCAIL-2 · FP16 · DPO</span></header>
  {config&&!config.worker_ready&&<p role="status" className="cr-hint">Worker ویدئو هنوز آماده یا متصل نیست؛ Job می‌تواند در صف بماند تا Replica مربوط به SCAIL-2 روشن شود.</p>}
  {configError&&<p role="alert" className="cr-alert">قابلیت هنوز روی Backend فعال نیست: {configError}</p>}
  {error&&<p role="alert" className="cr-alert">{error}</p>}
  {success&&<p role="status" className="cr-success">{success}</p>}
  <div className="cr-columns"><form onSubmit={submit} className="cr-form">
   <div className="cr-inputs"><UploadCard label="۱. ویدئوی اصلی" kind="video" file={files.video}
     onFile={file=>chooseFile('video',file)} meta={assets.video} loading={uploading==='video'} onUpload={()=>upload('video')}/>
    <UploadCard label="۲. تصویر کاراکتر جدید" kind="reference" file={files.reference}
     onFile={file=>chooseFile('reference',file)} meta={assets.reference} loading={uploading==='reference'} onUpload={()=>upload('reference')}/></div>
   <label className="cr-field">۳. توصیف کاراکتر و صحنه (اختیاری)
    <textarea rows="3" maxLength="1500" value={form.prompt} onChange={e=>update('prompt',e.target.value)}
      placeholder="A cinematic scene, natural lighting, realistic facial motion…"/></label>
   <label className="cr-field">تشخیص شخص در ویدئو
    <input value={form.detect_prompt} maxLength="100" onChange={e=>update('detect_prompt',e.target.value)}
      placeholder="a person"/><small>در نسخه اول، یک شخص اصلی شناسایی می‌شود؛ برای صحنه‌های چندنفره انتخاب دقیق فرد هنوز فعال نیست.</small></label>
   <div className="cr-settings"><h2>۴. تنظیمات تولید</h2>
    <div className="cr-field"><span>پروفایل کیفیت</span><div className="cr-toggle">
      <label><input type="radio" checked={form.quality==='quality'} onChange={()=>setForm(v=>({...v,quality:'quality',steps:24}))}/> کیفیت بالا · ۲۴ Step</label>
      <label><input type="radio" checked={form.quality==='fast'} onChange={()=>setForm(v=>({...v,quality:'fast',steps:4}))}/> Preview سریع · ۴ Step</label>
     </div></div>
    <label className="cr-field">Seed<input type="number" min="0" max="9223372036854775807" value={form.seed}
      onChange={e=>update('seed',e.target.value)}/></label>
    <label className="cr-check"><input type="checkbox" checked={form.preserve_audio} onChange={e=>update('preserve_audio',e.target.checked)}/> حفظ صدای ویدئوی اصلی</label>
    <label className="cr-check"><input type="checkbox" checked={form.confirmed_rights} onChange={e=>update('confirmed_rights',e.target.checked)}/>
      تأیید می‌کنم حق استفاده از ویدئو و تصویر و رضایت افراد مربوط را دارم.</label></div>
   <button className="cr-submit" disabled={!canSubmit}>{submitting?'در حال ثبت درخواست…':'✦ شروع جایگزینی کاراکتر'}</button>
   <p className="cr-hint">در حالت کیفیت بالا از مدل FP16 و LoRA مخصوص بهبود خروجی استفاده می‌شود. خروجی 16fps و حداکثر ۱۰ ثانیه است.</p>
  </form>
  <aside className="cr-preview"><h2>پیش‌نمایش ورودی‌ها</h2>
   {preview.video?<video src={preview.video} controls preload="metadata" playsInline aria-label="ویدئوی اصلی"/>:<div className="cr-empty">ویدئوی اصلی هنوز انتخاب نشده است</div>}
   {preview.reference?<img src={preview.reference} alt="شخصیت جایگزین"/>:<div className="cr-empty cr-ref">تصویر مرجع اینجا دیده می‌شود</div>}
   <p>خروجی، صحنه و حرکت را به‌صورت مولد بازسازی می‌کند؛ حفظ دقیق همه جزئیات تضمین نمی‌شود.</p>
  </aside></div>
  <section className="cr-history"><div className="cr-history-title"><h2>کارهای جایگزینی شخصیت</h2>
   <button type="button" onClick={()=>void refresh()}>به‌روزرسانی</button></div>
   {!jobs.length&&<p className="cr-empty">پس از اجرای اولین ویدئو، وضعیت آن اینجا نمایش داده می‌شود.</p>}
   <div className="cr-jobgrid">{jobs.map(job=><article key={job.id} className="cr-job"><div className="cr-jobtop"><strong>{job.quality==='quality'?'کیفیت بالا':'Preview سریع'}</strong>
     <span className={'cr-state cr-'+job.state}>{LABELS[job.state]||job.state}</span></div>
     <small>{new Date(job.created_at).toLocaleString('fa-IR')}</small>
     <p>{job.error||`مدل SCAIL-2 · ${job.steps} Step · تلاش ${job.attempts}`}</p>
     {job.state==='succeeded'&&<video className="cr-result" controls preload="metadata" src={`${ROOT}/jobs/${job.id}/preview`} aria-label="ویدئوی خروجی"/>}
     <div className="cr-inline">{job.state==='succeeded'&&<button onClick={()=>void download(job)}>دانلود MP4</button>}
      {ACTIVE.has(job.state)&&<button onClick={()=>void action(job,'cancel')}>لغو Job</button>}
      {['failed','stalled'].includes(job.state)&&<button onClick={()=>void action(job,'retry')}>تلاش مجدد</button>}</div>
    </article>)}</div>
  </section>
  <footer className="cr-footer"><AppLink to="/edit/video">بازگشت به ابزارهای ویدئو</AppLink> · <AppLink to="/library">کتابخانه شخصی</AppLink></footer>
 </section>;
}
