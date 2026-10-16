import React, {useEffect, useRef, useState} from 'react';
import {useAuth} from '../../auth/session.jsx';
import {AppLink} from '../../layouts/Layouts.jsx';

/** Clearly labelled pilot; DOES NOT use the verified Model Registry catalog. */
async function request(path, {method='GET',csrfToken,body,signal}={}) {
  if (path !== '/api/legacy-direct/workflows' && path !== '/api/jobs' && path !== '/api/uploads') {
    throw Error('Unexpected API path');
  }
  const headers={Accept:'application/json'};
  if (csrfToken) headers['X-CSRF-Token']=csrfToken;
  if (body!==undefined && !(body instanceof FormData)) headers['Content-Type']='application/json';
  const response=await fetch(path,{method,headers,credentials:'same-origin',cache:'no-store',signal,
    ...(body!==undefined?{body:body instanceof FormData?body:JSON.stringify(body)}:{})});
  let result=null;try {result=await response.json();} catch {}
  if (!response.ok) throw Error(typeof result?.detail==='string'?result.detail:`HTTP ${response.status}`);
  return result;
}
const defaultValue=(field)=>field.type==='integer'?1:field.type==='number'?1:field.type==='boolean'?false:'';
function cast(field,value){
  if (field.type==='integer') {if(!/^-?\d+$/.test(String(value)))throw Error(`${field.key}: enter an integer`);const n=Number(value);if(!Number.isSafeInteger(n))throw Error(`${field.key}: number too large`);return n;}
  if (field.type==='number'){const n=Number(value);if(!Number.isFinite(n))throw Error(`${field.key}: invalid number`);return n;}
  if(field.type==='boolean')return Boolean(value);
  return String(value??'');
}
export function LegacyDirectPanel(){
  const {session,epoch,mutationToken}=useAuth();
  const admin=Boolean(session.user?.roles?.some(x=>x==='admin'||x==='superadmin'));
  const [data,setData]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState('');
  const [selected,setSelected]=useState(''),[variables,setVariables]=useState({}),[busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');const pending=useRef(null);
  useEffect(()=>{
    if(!admin)return;
    const controller=new AbortController();setLoading(true);setError('');setMessage('');
    request('/api/legacy-direct/workflows',{signal:controller.signal})
      .then(value=>{if(!controller.signal.aborted)setData(value);})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[admin,epoch,session.user?.id]);
  if(!admin)return null;
  const workflow=data?.items?.find(x=>x.id===selected);
  function choose(id){setSelected(id);setMessage('');setError('');pending.current=null;
    const item=data?.items?.find(x=>x.id===id);setVariables(Object.fromEntries((item?.fields||[]).map(f=>[f.key,defaultValue(f)])));}
  function change(key,value){setVariables(old=>({...old,[key]:value}));pending.current=null;setMessage('');}
  async function upload(file,field){if(!file)return;setBusy(true);setError('');try{
    const form=new FormData();form.append('file',file);const response=await request('/api/uploads',{method:'POST',body:form,csrfToken:await mutationToken()});
    change(field,'asset:'+response.asset_id);
  }catch(e){setError(e.message);}finally{setBusy(false);}}
  async function submit(e){e.preventDefault();if(!workflow?.can_submit||busy)return;
    setBusy(true);setError('');setMessage('');
    try{
      const vars={};for(const f of workflow.fields)vars[f.key]=cast(f,variables[f.key]);
      if(!pending.current)pending.current=crypto.randomUUID();
      const response=await request('/api/jobs',{method:'POST',csrfToken:await mutationToken(),
        body:{contract_version:1,client_request_id:pending.current,workflow_id:workflow.id,
          workflow_version:workflow.graph_sha256,seed_mode:'fixed',variables:vars}});
      pending.current=null;setMessage(`Job ${response.id} در صف ثبت شد. وضعیت: ${response.state}`);
    }catch(e){setError(e.message); /* preserve idempotency key on uncertain network outcome */}
    finally{setBusy(false);}}
  return <section style={{border:'1px solid #5d7191',borderRadius:12,padding:18,marginBottom:24}} dir="rtl" aria-label="Legacy Direct Queue">
    <h2>اجرای Workflow قدیمی — مخصوص مدیر</h2>
    <p>این مسیر موقت از صف مستقیم Worker موجود استفاده می‌کند؛ مدل‌های این بخش <strong>تأیید Runtime در Registry ندارند</strong>. فقط Workflowهای دارای SHA تأییدشده توسط مدیر قابل ارسال‌اند و ممکن است GPU هزینه داشته باشد.</p>
    {loading&&<p role="status">در حال بررسی Workflowهای موجود…</p>}
    <label>Workflow
      <select value={selected} onChange={e=>choose(e.target.value)} style={{width:'100%',marginTop:6}}>
        <option value="">انتخاب Workflow</option>
        {(data?.items||[]).map(w=><option key={w.id} value={w.id}>{w.name} — {w.can_submit?'مجاز':'نیازمند تأیید مدیر'}</option>)}
      </select>
    </label>
    {data&&!data.items?.length&&<p>Workflow قدیمی در دیتابیس پیدا نشد.</p>}
    {workflow&&<div style={{marginTop:12}}>
      <p>مدل‌های مشاهده‌شده در Graph: {workflow.model_files.join('، ')||'نامشخص / پارامتری'} — وضعیت: تأییدنشده</p>
      <div style={{direction:'ltr',overflowWrap:'anywhere',fontFamily:'monospace',fontSize:12}}>
        {workflow.id}@{workflow.graph_sha256}
      </div>
      {!workflow.can_submit&&<p role="status">ارسال مسدود است: مدیر باید مقدار بالا را در OWNER_DIRECT_ALLOWLIST قرار دهد، Image فعال را در OWNER_DIRECT_IMAGE مشخص کند و پس از تست واقعی Worker فلگ OWNER_DIRECT_JOB_ENABLED را فعال کند.</p>}
      {workflow.can_submit&&<form onSubmit={submit} style={{marginTop:16}}>
        {workflow.fields.map(f=><label key={f.key} style={{display:'block',marginBottom:12}}>{f.key}
          {f.type==='reference'?<><input type="file" accept="image/png,image/jpeg,image/webp,image/gif" disabled={busy} onChange={e=>upload(e.target.files?.[0],f.key)}/><small dir="ltr" style={{display:'block',overflowWrap:'anywhere'}}>{variables[f.key]||'فایلی بارگذاری نشده'}</small></>
          :f.type==='boolean'?<input type="checkbox" checked={Boolean(variables[f.key])} onChange={e=>change(f.key,e.target.checked)}/>
          :f.key.startsWith('prompt.')?<textarea rows={3} required value={variables[f.key]??''} onChange={e=>change(f.key,e.target.value)} style={{width:'100%'}}/>
          :<input dir="auto" type={f.type==='integer'||f.type==='number'?'number':'text'} step={f.type==='integer'?'1':f.type==='number'?'any':undefined} value={variables[f.key]??''} onChange={e=>change(f.key,e.target.value)} style={{width:'100%'}}/>}
        </label>)}
        <button disabled={busy} type="submit">{busy?'در حال ثبت…':'ثبت Job در صف مستقیم'}</button>
      </form>}
    </div>}
    {error&&<p role="alert" style={{color:'#ff9292'}}>{error}</p>}
    {message&&<p role="status">{message} — <AppLink to="/jobs">مشاهده کارهای من</AppLink></p>}
  </section>;
}
