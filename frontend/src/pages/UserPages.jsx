import React,{useEffect,useRef,useState} from 'react';
import {useAuth} from '../auth/session.jsx';
import {authRequest,messageForStatus} from '../auth/api.js';
import {AppLink} from '../layouts/Layouts.jsx';

function SafeState({children}){return <div className="p04-state" role="status">{children}</div>;}
function JobStatus({value}){return <span className="p04-status">{String(value||'unknown').replaceAll('_',' ')}</span>;}
function time(value){if(!value)return 'ثبت نشده';const t=new Date(value);return Number.isNaN(+t)?'نامشخص':t.toLocaleString('fa-IR');}

export function Dashboard(){const {session}=useAuth();return <section className="p04-landing"><h1>سلام، {session.user?.display_name||'کاربر'}</h1><p>فضای شخصی برای پیگیری کارها و مدیریت تصاویر ساخته‌شده.</p><div className="p04-quick"><AppLink to="/jobs">مشاهده کارهای من ←</AppLink><AppLink to="/library">کتابخانه خصوصی ←</AppLink><AppLink to="/create/image">ساخت تصویر ←</AppLink></div></section>;}

export function JobsPage({selectedId}){
  const {ownerClient,epoch}=useAuth();const [items,setItems]=useState([]),[state,setState]=useState('loading'),[error,setError]=useState('');const [cursor,setCursor]=useState(null),[q,setQ]=useState('');const inflight=useRef(null);
  async function load(nextCursor=null){
    inflight.current?.abort();const controller=new AbortController();inflight.current=controller;setState('loading');setError('');
    try{
      const params=new URLSearchParams({limit:'24'});if(q)params.set('q',q);if(nextCursor)params.set('cursor',nextCursor);
      const response=await ownerClient.request(`/api/jobs/history?${params}`,{signal:controller.signal});
      if(!response.ok)throw Object.assign(new Error(messageForStatus(response.status)),{status:response.status});
      const data=await response.json();if(controller.signal.aborted)return;
      setItems(existing=>nextCursor?[...existing,...(data.items||[])]:data.items||[]);setCursor(data.next_cursor||null);setState('ready');
    }catch(e){if(!controller.signal.aborted){setState('error');setError(e.message);}}
  }
  useEffect(()=>{void load();return()=>{inflight.current?.abort();setItems([]);};},[epoch]);
  if(selectedId)return <JobDetails selectedId={selectedId}/>;
  return <section><h1>کارهای من</h1><p className="p04-muted">فقط کارهای مالک نشست فعلی نمایش داده می‌شوند.</p>
    <form className="p04-search" onSubmit={e=>{e.preventDefault();void load();}}><label htmlFor="jobs-query">جستجو در کارهای خودم</label><input id="jobs-query" value={q} onChange={e=>setQ(e.target.value)} maxLength={160} placeholder="عبارت پرامپت یا ابزار"/><button type="submit" disabled={state==='loading'}>جستجو</button></form>
    {state==='loading'&&<SafeState>در حال بارگذاری کارها…</SafeState>}
    {state==='error'&&<div role="alert" className="p04-alert">{error}<button type="button" onClick={()=>void load()}>تلاش دوباره</button></div>}
    {state==='ready'&&!items.length&&<SafeState>هنوز کاری وجود ندارد یا نتیجه‌ای پیدا نشد.</SafeState>}
    <div className="p04-jobs-grid">{items.map(item=><article className="p04-job" key={item.id}><div><JobStatus value={item.state}/><h2>{item.workflow_id||'تولید تصویر'}</h2><p className="p04-muted">{time(item.created_at)}</p><p className="p04-muted">خروجی موجود: {item.output_summary?.available??'نامشخص'}</p></div><AppLink to={`/jobs/${encodeURIComponent(item.id)}`}>جزئیات</AppLink></article>)}</div>
    {state==='ready'&&cursor&&<button type="button" onClick={()=>void load(cursor)}>نمایش بیشتر</button>}
  </section>;
}
export function JobDetails({selectedId}){
  const {ownerClient,epoch}=useAuth(),[job,setJob]=useState(null),[state,setState]=useState('loading'),[error,setError]=useState('');
  useEffect(()=>{let active=true;const controller=new AbortController();setJob(null);setState('loading');
    ownerClient.request(`/api/jobs/${encodeURIComponent(selectedId)}`,{signal:controller.signal}).then(async r=>{if(!r.ok)throw new Error(messageForStatus(r.status));return r.json();}).then(data=>{if(active){setJob(data);setState('ready');}}).catch(e=>{if(active){setState('error');setError(e.message);}});
    return()=>{active=false;controller.abort();setJob(null);};},[selectedId,epoch]);
  return <section><AppLink to="/jobs">← بازگشت به لیست</AppLink><h1>جزئیات کار</h1>
    {state==='loading'&&<SafeState>در حال خواندن اطلاعات خصوصی کار…</SafeState>}
    {state==='error'&&<div className="p04-alert" role="alert">{error}</div>}
    {job&&<div className="p04-job"><JobStatus value={job.state}/><h2>{job.workflow_id}</h2><p>ایجادشده: {time(job.created_at)}</p><p>شروع: {time(job.started_at)}</p><p>پایان: {time(job.finished_at)}</p><p>خروجی‌ها: {job.output_summary?.available??0}</p><div dir="ltr" className="p04-prompt"><strong>Prompt</strong><pre>{job.snapshot?.positive_prompt||'Not available'}</pre></div>{job.assets?.map(a=><div key={a.asset_id} className="p04-asset"><span>{a.mime_type||'Output'}</span><a href={a.download_url} rel="noreferrer">دریافت خروجی از مسیر مجاز</a></div>)}</div>}
  </section>;
}
export function LibraryPage(){const {ownerClient,epoch}=useAuth();const [state,setState]=useState('loading'),[items,setItems]=useState([]),[error,setError]=useState('');
  useEffect(()=>{let valid=true;const ctrl=new AbortController();setState('loading');setItems([]);
    ownerClient.request('/api/assets?limit=50',{signal:ctrl.signal}).then(async r=>{if(!r.ok)throw Error(messageForStatus(r.status));return r.json();}).then(d=>{if(valid){setItems(d.items||[]);setState('ready');}}).catch(e=>{if(valid){setError(e.message);setState('error');}});
    return()=>{valid=false;ctrl.abort();setItems([]);};},[epoch]);
  return <section><h1>کتابخانه خصوصی</h1><p className="p04-muted">دسترسی به فایل‌ها فقط با احراز مالکیت انجام می‌شود.</p>{state==='loading'&&<SafeState>در حال بارگذاری فایل‌ها…</SafeState>}{state==='error'&&<p className="p04-alert" role="alert">{error}</p>}{state==='ready'&&!items.length&&<SafeState>هنوز فایلی وجود ندارد.</SafeState>}<div className="p04-jobs-grid">{items.map(a=><article className="p04-job" key={a.asset_id}><strong>{a.mime_type||'Media'}</strong><p>{time(a.created_at)}</p><p>فایل خصوصی</p></article>)}</div></section>;
}
export function CreateImagePage(){return <section className="p04-landing"><h1>ساخت و ویرایش تصویر</h1><p>رابط کاربری آماده است، اما ایجاد Job برای حساب‌های چندکاربره هنوز از Gate امنیتی عبور نکرده است.</p><div className="p04-alert" role="status">در حال حاضر امکان Generate/Retry با نشست کاربر فعال نیست؛ برای جلوگیری از استفاده از توکن مدیریت و مصرف GPU بدون تأیید مالکیت، اجرای درخواست مسدود است.</div><AppLink to="/jobs">مشاهده کارهای موجود</AppLink></section>;}
export function AccountSecurityPage(){const {session,mutationToken,logout,epoch}=useAuth();const [rows,setRows]=useState([]),[state,setState]=useState('loading'),[error,setError]=useState('');
  useEffect(()=>{let valid=true;setState('loading');authRequest('/sessions').then(d=>{if(valid){setRows(d.sessions||[]);setState('ready');}}).catch(e=>{if(valid){setError(e.message);setState('error');}});return()=>{valid=false;};},[epoch]);
  async function revoke(id){setError('');try{const csrfToken=await mutationToken();await authRequest(`/sessions/${encodeURIComponent(id)}`,{method:'DELETE',csrfToken});setRows(x=>x.filter(s=>s.id!==id));if(rows.find(s=>s.id===id)?.current){await logout();window.location.assign('/login');}}catch(e){setError(e.message);}}
  return <section><h1>امنیت حساب</h1><p>{session.user?.email}</p>{state==='loading'&&<SafeState>در حال بررسی نشست‌های فعال…</SafeState>}{state==='error'&&<p role="alert" className="p04-alert">{error}</p>}{rows.map(s=><article className="p04-job" key={s.id}><strong>نشست {s.current?'فعلی':'دیگر'}</strong><p>آخرین فعالیت: {time(s.last_seen_at)}</p><p>انقضا: {time(s.expires_at)}</p><button type="button" onClick={()=>void revoke(s.id)}>ابطال نشست</button></article>)}</section>;
}
export function UnsupportedPage({title}){return <section className="p04-landing"><h1>{title||'این قابلیت'}</h1><p>این مسیر در نقشه ناوبری آماده شده، اما پیاده‌سازی کامل آن مربوط به مرحله بعدی است.</p><AppLink to="/dashboard">بازگشت به داشبورد</AppLink></section>;}
export function AdminPage(){return <section className="p04-landing"><h1>تنظیمات مدیریت</h1><p>تا قبل از سیاست مصوب RBAC، مجوز مشاهده داده خصوصی و مسیر امن مدیریت GPU، کنترل‌های Legacy با توکن مشترک در پوسته کاربران فعال نشده‌اند.</p><div className="p04-alert" role="status">برای جلوگیری از نمایش محتوای کاربران دیگر، این پنل فعلاً فقط نمای اطلاع‌رسانی است.</div></section>;}
