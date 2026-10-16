import React, {useCallback, useEffect, useRef, useState} from 'react';
import {useAuth} from '../../auth/session.jsx';
import {AppLink} from '../../layouts/Layouts.jsx';

/** User-scoped API only. No internal tokens or Salad secrets in the browser. */
async function request(path, {method='GET', csrfToken, body, signal}={}) {
  if (![
    '/api/legacy-direct/workflows', '/api/jobs', '/api/uploads',
    '/api/self-service/gpu', '/api/self-service/gpu/start',
    '/api/self-service/gpu/one', '/api/self-service/gpu/zero',
    '/api/self-service/gpu/stop',
  ].includes(path)) throw Error('Unexpected API path');
  const headers={Accept:'application/json'};
  if (csrfToken) headers['X-CSRF-Token']=csrfToken;
  if (body !== undefined && !(body instanceof FormData)) headers['Content-Type']='application/json';
  const response=await fetch(path,{method,headers,credentials:'same-origin',cache:'no-store',signal,
    ...(body!==undefined ? {body:body instanceof FormData ? body:JSON.stringify(body)} : {})});
  let result=null;
  try { result=await response.json(); } catch { /* body can be empty */ }
  if (!response.ok) throw Error(typeof result?.detail==='string' ? result.detail : `HTTP ${response.status}`);
  return result;
}

const sectionStyle={border:'1px solid #415571',borderRadius:14,padding:20,marginBottom:22};
const buttonStyle={padding:'9px 15px',border:'1px solid #557296',borderRadius:9,cursor:'pointer'};
const defaultValue=f=>f.type==='integer'?1:f.type==='number'?1:f.type==='boolean'?false:'';
function cast(field,value){
  if(field.type==='integer'){
    if(!/^-?\d+$/.test(String(value))) throw Error(`${field.key}: مقدار صحیح وارد کنید.`);
    const n=Number(value);
    if(!Number.isSafeInteger(n)) throw Error(`${field.key}: عدد خارج از محدوده است.`);
    return n;
  }
  if(field.type==='number'){
    const n=Number(value);
    if(!Number.isFinite(n)) throw Error(`${field.key}: عدد معتبر وارد کنید.`);
    return n;
  }
  if(field.type==='boolean')return Boolean(value);
  return String(value??'');
}

function GpuPanel(){
  const {session, epoch, mutationToken}=useAuth();
  const [status,setStatus]=useState(null),[busy,setBusy]=useState('');
  const [error,setError]=useState(''),[notice,setNotice]=useState('');
  const [loading,setLoading]=useState(true);
  const refresh=useCallback(async signal=>{
    try{
      const info=await request('/api/self-service/gpu',{signal});
      if(!signal?.aborted){setStatus(info);setError('');}
    }catch(err){if(!signal?.aborted)setError(err.message);}
    finally{if(!signal?.aborted)setLoading(false);}
  },[]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);
    refresh(controller.signal);
    const interval=setInterval(()=>refresh(controller.signal),12000);
    return()=>{controller.abort();clearInterval(interval);};
  },[refresh,epoch,session.user?.id]);
  async function operate(action){
    if(busy)return;
    setBusy(action);setError('');setNotice('');
    try{
      const csrfToken=await mutationToken();
      await request('/api/self-service/gpu/'+action,{method:'POST',csrfToken});
      setNotice('درخواست به Salad ارسال شد؛ برای وضعیت نهایی چند لحظه منتظر بمانید.');
      await refresh();
    }catch(err){setError(err.message);}finally{setBusy('');}
  }
  const queue=status?.queue??{};
  const locked=Boolean(status?.pending_change||busy||loading||!status?.enabled);
  const haveJobs=Boolean(queue.waiting||queue.active||queue.uncertain);
  const state=String(status?.status||'نامشخص').toLowerCase();
  const stopped=state==='stopped';
  const instances=status?.instances||[];
  return <section dir="rtl" style={sectionStyle} aria-label="کنترل GPU">
    <h2 style={{marginTop:0}}>کنترل GPU <small style={{fontSize:13,fontWeight:400}}>مستقیم از Salad</small></h2>
    <p>برای روشن یا خاموش‌کردن GPU نیازی به تأیید مدیر ندارید. این GPU در تنظیمات فعلی بین کاربران مشترک است؛ هنگام وجود Job در صف یا در حال اجرا، خاموش‌کردن آن مجاز نیست.</p>
    <div style={{display:'flex',gap:12,flexWrap:'wrap',alignItems:'center',marginBottom:12}}>
      <strong>وضعیت: {loading?'در حال بررسی…':status?.status||'نامشخص'}</strong>
      <span>GPU: {status?.replicas??'–'}</span>
      <span>آماده: {instances.filter(i=>i.ready===true).length}</span>
      <span>صف: {queue.waiting??'–'}</span>
      <span>در حال اجرا: {queue.active??'–'}</span>
      {status?.pending_change&&<span>در انتظار تأیید وضعیت توسط Salad</span>}
    </div>
    <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
      <button type="button" style={buttonStyle} disabled={locked||!stopped} onClick={()=>operate('start')}>روشن‌کردن گروه</button>
      <button type="button" style={buttonStyle} disabled={locked||stopped||Number(status?.replicas)>=1} onClick={()=>operate('one')}>فعال‌کردن ۱ GPU</button>
      <button type="button" style={buttonStyle} disabled={locked||stopped||haveJobs||!Number(status?.replicas)||status?.keep_warm} onClick={()=>operate('zero')}>توقف GPU (صفر Replica)</button>
      <button type="button" style={buttonStyle} disabled={locked||stopped||haveJobs||status?.keep_warm} onClick={()=>operate('stop')}>خاموش‌کردن گروه</button>
      <button type="button" style={buttonStyle} disabled={Boolean(busy)} onClick={()=>{setLoading(true);refresh();}}>بروزرسانی وضعیت</button>
    </div>
    {status?.keep_warm&&<p style={{opacity:.8}}>Keep Warm فعال است. برای خاموش‌کردن باید ابتدا سیاست نگه‌داری GPU در تنظیمات زیرساخت تغییر کند.</p>}
    {status?.enabled===false&&<p role="alert">Direct Queue در سرور فعال نیست.</p>}
    {notice&&<p role="status">{notice}</p>}
    {error&&<p role="alert" style={{color:'#ff9999'}}>{error}</p>}
  </section>;
}

/** Uses existing saved graphs; no admin allowlist, no verified-registry dependency. */
export function LegacyDirectPanel(){
  const {session,epoch,mutationToken}=useAuth();
  const [catalog,setCatalog]=useState(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [selected,setSelected]=useState(''),[variables,setVariables]=useState({}),[busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');const pending=useRef(null);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('');setMessage('');
    request('/api/legacy-direct/workflows',{signal:controller.signal})
      .then(value=>{
        if(controller.signal.aborted)return;
        setCatalog(value);
        setSelected(old=>value.items?.some(x=>x.id===old)?old:(value.items?.[0]?.id||''));
      })
      .catch(err=>{if(!controller.signal.aborted)setError(err.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[epoch,session.user?.id]);
  const workflow=catalog?.items?.find(x=>x.id===selected);
  useEffect(()=>{
    pending.current=null;
    setVariables(Object.fromEntries((workflow?.fields||[]).map(f=>[f.key,defaultValue(f)])));
  },[selected,workflow?.graph_sha256]);
  function change(key,value){setVariables(old=>({...old,[key]:value}));pending.current=null;setMessage('');}
  async function upload(file,field){
    if(!file)return;
    setBusy(true);setError('');
    try{
      const form=new FormData();form.append('file',file);
      const response=await request('/api/uploads',{method:'POST',body:form,csrfToken:await mutationToken()});
      change(field,'asset:'+response.asset_id);
    }catch(err){setError(err.message);}finally{setBusy(false);}
  }
  async function submit(e){
    e.preventDefault();if(!workflow?.can_submit||busy)return;
    setBusy(true);setError('');setMessage('');
    try{
      const vars={};for(const f of workflow.fields)vars[f.key]=cast(f,variables[f.key]);
      if(!pending.current)pending.current=crypto.randomUUID();
      const response=await request('/api/jobs',{method:'POST',csrfToken:await mutationToken(),
        body:{contract_version:1,client_request_id:pending.current,workflow_id:workflow.id,
          workflow_version:workflow.graph_sha256,seed_mode:'fixed',variables:vars}});
      pending.current=null;
      setMessage(`درخواست ثبت شد (${response.state}). شناسه: ${response.id}`);
    }catch(err){setError(err.message);}finally{setBusy(false);}
  }
  return <div dir="rtl">
    <GpuPanel/>
    <section aria-label="ساخت یا ویرایش تصویر" style={sectionStyle}>
      <h2 style={{marginTop:0}}>ساخت و ویرایش تصویر</h2>
      <p>یکی از Workflowهای ذخیره‌شده را انتخاب کنید، تنظیمات را وارد کنید و تولید را آغاز کنید. نیازی به تأیید دستی مدل یا Workflow نیست. اگر فایل مدل در Worker موجود نباشد، خطا در نتیجه Job مشخص خواهد شد.</p>
      {loading&&<p role="status">در حال بارگذاری Workflowها…</p>}
      <label htmlFor="direct-workflow">Workflow</label>
      <select id="direct-workflow" value={selected} onChange={e=>{setSelected(e.target.value);setMessage('');setError('');pending.current=null;}}
        style={{width:'100%',margin:'8px 0 18px',padding:10}}>
        {!catalog?.items?.length&&<option value="">Workflow موجود نیست</option>}
        {(catalog?.items||[]).map(w=><option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
      {workflow&&<>
        <p style={{opacity:.75}}>فایل‌های مدل تعریف‌شده در Workflow: {workflow.model_files.join('، ')||'نامشخص'}</p>
        {workflow.can_submit?<form onSubmit={submit}>
          {workflow.fields.map(f=><label key={f.key} style={{display:'block',margin:'12px 0'}}>
            <span dir="auto">{f.key}</span>
            {f.type==='reference'?<><input type="file" accept="image/png,image/jpeg,image/webp,image/gif" disabled={busy}
              onChange={e=>upload(e.target.files?.[0],f.key)}/><small style={{display:'block'}} dir="ltr">{variables[f.key]||'تصویر مرجع بارگذاری نشده'}</small></>
              :f.type==='boolean'?<input type="checkbox" checked={Boolean(variables[f.key])} onChange={e=>change(f.key,e.target.checked)}/>
              :f.key.startsWith('prompt.')?<textarea rows={3} required value={variables[f.key]??''} onChange={e=>change(f.key,e.target.value)} style={{display:'block',width:'100%',padding:10}}/>
              :<input dir="auto" type={f.type==='integer'||f.type==='number'?'number':'text'}
                step={f.type==='integer'?'1':f.type==='number'?'any':undefined}
                value={variables[f.key]??''} onChange={e=>change(f.key,e.target.value)} style={{display:'block',width:'100%',padding:10}}/>}
          </label>)}
          <button type="submit" disabled={busy} style={buttonStyle}>{busy?'در حال ارسال…':'شروع تولید تصویر'}</button>
        </form>:<p role="alert">Direct Queue هنوز در Backend پیکربندی نشده است.</p>}
      </>}
      {error&&<p role="alert" style={{color:'#ff9999'}}>{error}</p>}
      {message&&<p role="status">{message} — <AppLink to="/jobs">مشاهده کارها</AppLink></p>}
    </section>
  </div>;
}
