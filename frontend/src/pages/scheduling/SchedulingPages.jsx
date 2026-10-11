import React,{useEffect,useState} from 'react';
import {useAuth} from '../../auth/session.jsx';
import './scheduling.css';

import {schedulerRequest} from './schedulerClient.mjs';
function useScheduler(paths){
 const {session,epoch}=useAuth(),[state,setState]=useState({loading:true,error:'',items:[]});
 useEffect(()=>{const controller=new AbortController();setState({loading:true,error:'',items:[]});
  Promise.all(paths.map(p=>schedulerRequest(p,{signal:controller.signal}))).then(items=>{
   if(!controller.signal.aborted)setState({loading:false,error:'',items});
  }).catch(e=>{if(!controller.signal.aborted)setState({loading:false,error:e.message,items:[]});});
  return()=>controller.abort();
 },[session.user?.id,epoch,paths.join('|')]);return state;
}
export function UsagePage(){
 const s=useScheduler(['/api/v2/scheduling/me/queue-summary','/api/v2/scheduling/me/usage']);
 return <section className="s12" aria-label="سهمیه و مصرف شخصی"><h1>مصرف GPU و وضعیت صف من</h1>
  <p>اطلاعات این صفحه فقط مربوط به حساب جاری است. هزینه‌ها تخمینی هستند، نه موجودی حساب یا فاکتور.</p>
  {s.loading&&<p role="status">در حال دریافت وضعیت خصوصی صف…</p>}
  {s.error&&<p role="alert">{s.error}</p>}
  {!s.loading&&!s.error&&<div className="s12-grid">
   <article><h2>صف من</h2><p>در انتظار تخصیص: {s.items[0].eligible}</p><p>متوقف‌شده به‌دلیل سیاست: {s.items[0].held}</p><p>ETA: نامشخص تا ثبت داده معتبر Worker</p></article>
   <article><h2>مصرف تخمینی</h2><p>زمان تخصیص: {s.items[1].allocated_seconds_estimate} ثانیه</p>
    <p>هزینه تخمینی: {s.items[1].cost_estimates_minor?Object.entries(s.items[1].cost_estimates_minor).map(([c,v])=>`${(v/100).toFixed(2)} ${c}`).join('، '):'داده معتبر موجود نیست'}</p>
    <p>هزینه قطعی Provider: {s.items[1].provider_actual_minor?Object.entries(s.items[1].provider_actual_minor).map(([c,v])=>`${(v/100).toFixed(2)} ${c}`).join('، '):'اطلاعات فاکتور تأیید نشده است'}</p></article>
  </div>}
 </section>;
}
export function InfrastructurePage(){
 const s=useScheduler(['/api/v2/scheduling/admin/infrastructure','/api/v2/scheduling/admin/decisions',
 '/api/v2/scheduling/admin/allocations']);
 const {mutationToken}=useAuth();const [action,setAction]=useState(''),[reason,setReason]=useState('operator_review'),[op,setOp]=useState('start'),[message,setMessage]=useState('');
 async function propose(e){e.preventDefault();setMessage('');try{const csrfToken=await mutationToken();const r=await schedulerRequest('/api/v2/scheduling/admin/scale-intents',
  {method:'POST',csrfToken,body:{revision_id:action,action:op,reason_code:reason,acknowledge_non_executing_preview:true}});
  setMessage(`درخواست محلی ثبت شد (${r.state}). این فرمان به Salad ارسال نشده است.`);
 }catch(err){setMessage(err.message);}}
 return <section className="s12" aria-label="زیرساخت و صف GPU"><h1>مدیریت زیرساخت GPU</h1>
  <p role="status">حالت آزمایشی: ثبت درخواست Start/Stop به‌معنی اجرای آن در Salad یا تأیید آمادگی مدل نیست.</p>
  {s.loading&&<p>در حال دریافت وضعیت مشاهده‌شده…</p>}{s.error&&<p role="alert">{s.error}</p>}
  {!s.loading&&!s.error&&<>
   <div className="s12-grid">{s.items[0].instances.length?s.items[0].instances.map((i,n)=><article key={n}>
    <h2 dir="ltr">{i.revision_id}</h2><p>وضعیت Provider (غیر‌تأیید‌شده): {i.provider_state}</p>
    <p>آمادگی مدل: نامشخص</p><p>تغییر در انتظار تأیید: {i.provider_pending_change?'بله':'خیر'}</p>
    <p>تخصیص‌های باز: {i.active_allocations}</p></article>):<p>هیچ Instance ثبت‌شده‌ای وجود ندارد.</p>}</div>
   <h2>درخواست عملیات (بدون اتصال به Provider)</h2>
   <form onSubmit={propose} className="s12-form">
    <label>Profile Revision<select required value={action} onChange={e=>setAction(e.target.value)}><option value="">انتخاب کنید</option>
     {[...new Set(s.items[0].instances.map(i=>i.revision_id))].map(id=><option key={id} value={id}>{id}</option>)}</select></label>
    <label>عملیات<select value={op} onChange={e=>setOp(e.target.value)}><option value="start">درخواست Start</option><option value="stop">درخواست Stop</option><option value="drain">درخواست Drain</option><option value="hold">درخواست Hold</option></select></label>
    <label>دلیل<input value={reason} onChange={e=>setReason(e.target.value)} minLength={3} maxLength={60} pattern="[a-z][a-z0-9_]+" required/></label>
    <button type="submit">ثبت درخواست آزمایشی (بدون اجرای GPU)</button></form>
   {message&&<p role="status">{message}</p>}
   <h2>درخواست‌های در انتظار تأیید Provider</h2><p>{s.items[1].scale_intents.length} درخواست ثبت‌شده؛ نتیجه واقعی از این داده‌ها قابل‌استنتاج نیست.</p>
   <h2>تخصیص‌ها</h2><p>{s.items[2].allocations.length} رکورد (بدون Prompt و فایل‌های خصوصی).</p>
  </>}
 </section>;
}
