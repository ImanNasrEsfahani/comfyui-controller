import React,{useEffect,useRef,useState} from 'react';
import {useAuth} from '../../auth/session.jsx';
import {AppLink} from '../../layouts/Layouts.jsx';
import {navigate} from '../../app/navigation.js';
import {registryRequest} from '../registry/registryClient.js';
import {workflowRequest} from './workflowClient.js';
import './workflows.css';

function Problem({error}){return error?<p role="alert" className="p04-alert">{error}</p>:null;}
function AsyncData({loading,error,children}){return loading?<p role="status">در حال دریافت داده‌های نسخه‌دار…</p>:error?<Problem error={error}/>:children;}
export function WorkflowStudio(){
 const {session,epoch,mutationToken}=useAuth();
 const [templates,setTemplates]=useState([]),[models,setModels]=useState([]),[intent,setIntent]=useState('text2img'),[model,setModel]=useState(''),[title,setTitle]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState('');
 useEffect(()=>{const ctrl=new AbortController();setLoading(true);setError('');setTemplates([]);setModels([]);
  Promise.all([workflowRequest('/api/v2/semantic-workflow-templates',{signal:ctrl.signal}),registryRequest('/api/catalog/models',{signal:ctrl.signal})]).then(([a,b])=>{if(!ctrl.signal.aborted){setTemplates(a.items||[]);setModels(b.items||[]);setLoading(false)}}).catch(e=>{if(!ctrl.signal.aborted){setError(e.message);setLoading(false)}});
  return()=>ctrl.abort();},[epoch,session.user?.id]);
 async function create(e){e.preventDefault();setError('');setBusy(true);
  try{const csrfToken=await mutationToken();const tpl=await workflowRequest(`/api/v2/semantic-workflow-templates/${intent}`);
   const created=await workflowRequest('/api/v2/semantic-workflows',{method:'POST',csrfToken,body:{title:title.trim(),intent,model_version_id:model,scope:'user',graph:tpl.graph}});
   navigate(`/workflows/${encodeURIComponent(created.id)}/versions`);
  }catch(e){setError(e.field_path?`${e.message} · ${e.field_path}`:e.message)}finally{setBusy(false)}
 }
 return <section className="p09-area"><h1>Workflow Studio — نسخه آزمایشی</h1><p>ساخت Workflow فقط با Template تأییدشده در Backend؛ هنوز اجرای GPU فعال نیست. ویرایش بصری گراف در مرحله بعد تکمیل می‌شود.</p>
  <AsyncData loading={loading} error={error}>{templates.length?<form className="p09-form" onSubmit={create}>
   <label>نوع Workflow<select value={intent} onChange={e=>setIntent(e.target.value)}>{templates.map(x=><option key={x.intent} value={x.intent}>{x.label} — تأیید Runtime: نامشخص</option>)}</select></label>
   <label>مدل فهرست‌شده<select value={model} onChange={e=>setModel(e.target.value)} required><option value="">انتخاب مدل</option>{models.map(m=><option value={m.id} key={m.id}>{m.name}</option>)}</select></label>
   <label>عنوان<input value={title} onChange={e=>setTitle(e.target.value)} maxLength={150} required placeholder="نام پروژه"/></label>
   <button type="submit" disabled={!model||busy}>{busy?'در حال ذخیره…':'ایجاد Draft خصوصی'}</button></form>:<p>Template معتبر در دسترس نیست.</p>}</AsyncData>
  <AppLink to="/workflows">نسخه‌های ذخیره‌شده من</AppLink></section>
}
export function WorkflowList(){const {epoch,session}=useAuth(),[data,setData]=useState(null),[error,setError]=useState('');
 useEffect(()=>{const ctrl=new AbortController();setData(null);setError('');workflowRequest('/api/v2/semantic-workflows',{signal:ctrl.signal}).then(setData).catch(e=>{if(!ctrl.signal.aborted)setError(e.message)});return()=>ctrl.abort()},[epoch,session.user?.id]);
 return <section className="p09-area"><h1>Workflowهای من</h1><AppLink to="/workflows/new">ساخت Workflow جدید</AppLink><AsyncData loading={!data&&!error} error={error}>{!data?.items?.length?<p>هیچ Workflow شخصی ذخیره نشده است.</p>:<div className="p09-grid">{data.items?.map(w=><article className="p09-card" key={w.id}><strong>{w.title}</strong><p>{w.intent} · {w.scope}</p><AppLink to={`/workflows/${encodeURIComponent(w.id)}/versions`}>نمایش نسخه‌ها</AppLink></article>)}</div>}</AsyncData></section>}
function VersionCard({entry,onValidated,onPreview,onClone,canPublish}){
 const [values,setValues]=useState({}),[detail,setDetail]=useState(null),[error,setError]=useState(''),[result,setResult]=useState(null),[busy,setBusy]=useState(false),[requestKey,setRequestKey]=useState(null);
 const {mutationToken}=useAuth();const last=useRef(null);
 useEffect(()=>{let valid=true;setValues({});setDetail(null);setResult(null);setRequestKey(null);
  workflowRequest(`/api/v2/semantic-workflow-versions/${encodeURIComponent(entry.id)}`).then(v=>{if(valid)setDetail(v)}).catch(e=>{if(valid)setError(e.message)});return()=>{valid=false};},[entry.id]);
 function update(key,value){setValues(x=>({...x,[key]:value}));setRequestKey(null);setResult(null)}
 async function action(type){setBusy(true);setError('');setResult(null);
  try{const csrfToken=await mutationToken();const url=`/api/v2/semantic-workflow-versions/${encodeURIComponent(entry.id)}`;
   if(type==='validate'){await workflowRequest(url+'/validate',{method:'POST',csrfToken});onValidated();setResult({message:'اعتبارسنجی ساختاری موفق؛ Runtime هنوز تأیید نشده.'});}
   if(type==='compile'){
    // Read latest controlled form values in this event. Retain key only for a network retry of same *unchanged* draft.
    const key=requestKey||crypto.randomUUID();last.current=key;setRequestKey(key);const body={client_request_id:key,parameters:Object.fromEntries((detail?.input_schema||[]).filter(x=>values[x.key]!==undefined).map(x=>[x.key,x.type==='integer'&&x.key!=='seed'?Number(values[x.key]):x.type==='number'?Number(values[x.key]):values[x.key]]))};
    const r=await workflowRequest(url+'/compile-preview',{method:'POST',csrfToken,body});setRequestKey(key);setResult({message:'پیش‌نمایش غیر‌اجرایی ذخیره شد',...r});
   }
   if(type==='clone')onClone?.();
   if(type==='publish'){await workflowRequest(url+'/publish',{method:'POST',csrfToken,body:{confirm:true}});onValidated();}
  }catch(e){setError(e.field_path?`${e.message} · ${e.field_path}`:e.message)}finally{setBusy(false)}
 }
 return <article className="p09-card"><h2>نسخه {entry.version} · {entry.status}</h2><p>Checksum: <code dir="ltr">{entry.graph_checksum?.slice(0,14)}…</code></p>
  {entry.status!=='published'&&<button type="button" disabled={busy} onClick={()=>action('validate')}>Validate DAG</button>}
  {entry.status!=='draft'&&<details><summary>Compile Preview (بدون Job)</summary><div className="p09-form">{detail?.input_schema?.map(f=><label key={f.key}>{f.key} ({f.role})
    <input dir={f.type==='text'?'auto':'ltr'} aria-label={f.key} value={values[f.key]??''} placeholder={f.type==='image'?'شناسه Asset خصوصی':f.type==='integer'?'عدد مطابق مدل':'مقدار'} onChange={e=>update(f.key,e.target.value)}/></label>)}
    <button type="button" disabled={busy||!detail} onClick={()=>action('compile')}>ثبت پیش‌نمایش و Hash</button></div></details>}
  <Problem error={error}/>{result&&<p role="status">{result.message}{result.graph_hash&&<code dir="ltr"> · {result.graph_hash.slice(0,16)}…</code>}; GPU اجرا نشد.</p>}</article>
}
export function WorkflowVersions({id}){const {session,epoch,mutationToken}=useAuth(),[data,setData]=useState(null),[error,setError]=useState(''),[tick,setTick]=useState(0),[busy,setBusy]=useState(false);
 useEffect(()=>{const c=new AbortController();setData(null);setError('');workflowRequest(`/api/v2/semantic-workflows/${encodeURIComponent(id)}/versions`,{signal:c.signal}).then(setData).catch(e=>{if(!c.signal.aborted)setError(e.message)});return()=>c.abort()},[id,session.user?.id,epoch,tick]);
 async function clone(){setBusy(true);setError('');try{const csrfToken=await mutationToken();await workflowRequest(`/api/v2/semantic-workflows/${encodeURIComponent(id)}/versions`,{method:'POST',csrfToken});setTick(x=>x+1)}catch(e){setError(e.message)}finally{setBusy(false)}}
 return <section className="p09-area"><AppLink to="/workflows">← Workflowهای من</AppLink><h1>نسخه‌های Workflow</h1><p>نسخه Published تغییر نمی‌کند. برای ویرایش، نسخه جدید بسازید. Retry تاریخی Worker هنوز تأیید نشده است.</p>
  <button type="button" disabled={busy||!data} onClick={clone}>Clone به Draft جدید</button><AsyncData loading={!data&&!error} error={error}>{data?.items?.length?<div className="p09-grid">{data.items.map(v=><VersionCard key={v.id} entry={v} onValidated={()=>setTick(x=>x+1)}/>)}</div>:<p>نسخه‌ای پیدا نشد.</p>}</AsyncData></section>
}
