import React,{useEffect,useState} from 'react';
import {useAuth} from '../../auth/session.jsx';
import {mediaRequest} from './mediaClient.js';
import {AppLink} from '../../layouts/Layouts.jsx';
export function Phase06JobDetails({id}){
 const {ownerClient,epoch}=useAuth(),[job,setJob]=useState(null),[error,setError]=useState('');
 useEffect(()=>{let live=true;const ctrl=new AbortController();setJob(null);setError('');
  mediaRequest(ownerClient,`/api/jobs/${encodeURIComponent(id)}`,{signal:ctrl.signal}).then(v=>{if(live)setJob(v)}).catch(e=>{if(live)setError(e.message)});
  return()=>{live=false;ctrl.abort()};
 },[id,epoch,ownerClient]);
 return <section className="p06-library"><AppLink to="/jobs">کارهای من</AppLink><h1>جزئیات Job</h1>{!job&&!error&&<p role="status">در حال دریافت وضعیت از سرور…</p>}{error&&<p role="alert">{error}</p>}
 {job&&<><div className="p06-detail"><p>وضعیت: <strong>{job.state}</strong></p><p>Workflow: {job.workflow_id}</p><p>شروع: {job.started_at||'ثبت نشده'}</p><p>پایان: {job.finished_at||'ثبت نشده'}</p><p>خروجی تأییدشده: {job.output_summary?.available??'نامشخص'}</p>
  <details><summary>Snapshot و Prompt</summary><pre dir="auto">{job.snapshot?.positive_prompt||'داده‌ای ثبت نشده'}</pre></details></div>
  <div className="p06-grid">{(job.assets||[]).map(a=><article className="p06-card" key={a.asset_id}><strong>{a.mime_type||'خروجی'}</strong><AppLink to={`/library/${encodeURIComponent(a.asset_id)}`}>مشاهده خروجی در کتابخانه</AppLink></article>)}</div>
  <p>Retry و Generate تا تکمیل کنترل مالکیت در Backend غیرفعال است.</p>
 </>}
 </section>;
}
