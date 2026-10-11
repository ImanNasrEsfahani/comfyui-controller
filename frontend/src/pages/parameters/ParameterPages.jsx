import React,{useEffect,useMemo,useRef,useState} from 'react';
import {useAuth} from '../../auth/session.jsx';
import {AppLink} from '../../layouts/Layouts.jsx';
import {fieldDefaults,parameterPath,parametersRequest,removeUnsupported,safeFields,seedDecimal} from './parametersClient.js';
import './parameters.css';

function usePrivate(path){
 const {session,epoch}=useAuth(),[retry,setRetry]=useState(0),[state,setState]=useState({status:'loading',data:null,error:''});
 useEffect(()=>{if(!path){setState({status:'ready',data:null,error:''});return;}
  const ctrl=new AbortController();setState({status:'loading',data:null,error:''});
  parametersRequest(path,{signal:ctrl.signal}).then(d=>{if(!ctrl.signal.aborted)setState({status:'ready',data:d,error:''});}).catch(e=>{if(!ctrl.signal.aborted)setState({status:'error',data:null,error:e.message});});
  return()=>ctrl.abort();
 },[path,epoch,session.user?.id,retry]);return {...state,retry:()=>setRetry(v=>v+1)};
}
function State({source,children}){if(source.status==='loading')return <p role="status">در حال دریافت اطلاعات مدل…</p>;
 if(source.status==='error')return <p role="alert" className="p08-error">{source.error} <button type="button" onClick={source.retry}>تلاش دوباره</button></p>;
 return children(source.data);}
const uuid=()=>{if(!globalThis.crypto?.randomUUID)throw Error('مرورگر برای شناسه امن درخواست پشتیبانی لازم را ندارد.');return globalThis.crypto.randomUUID();};
function DynamicField({field,value,onChange,error}){
 const id='p08-'+field.key.replace(/[^A-Za-z0-9_-]/g,'-');const type=field.type;
 let control=null;
 if(type==='boolean')control=<input id={id} type="checkbox" checked={value===true} onChange={e=>onChange(e.target.checked)}/>;
 else if(type==='enum')control=<select id={id} value={value??''} onChange={e=>onChange(e.target.value)} required={field.required}><option value="">انتخاب کنید</option>{(field.options||[]).map(x=><option key={x} value={x}>{x}</option>)}</select>;
 else if(type==='multiselect')control=<select id={id} multiple value={Array.isArray(value)?value:[]} onChange={e=>onChange([...e.target.selectedOptions].map(o=>o.value))}>{(field.options||[]).map(x=><option key={x} value={x}>{x}</option>)}</select>;
 else if(type==='text')control=<textarea dir="auto" id={id} value={value??''} onChange={e=>onChange(e.target.value)} rows={4} required={field.required}/>;
 else if(type==='seed')control=<input dir="ltr" id={id} inputMode="numeric" pattern="[0-9]*" value={value??''} onChange={e=>onChange(e.target.value)} placeholder="0…18446744073709551615"/>;
 else control=<input dir={type==='string'?'auto':'ltr'} id={id} type={type==='number'||type==='integer'?'number':'text'} min={field.min} max={field.max} step={field.step|| (type==='integer'?1:'any')} value={value??''} required={field.required} onChange={e=>{const val=e.target.value;onChange(val===''?'':(type==='integer'?Number.parseInt(val,10):type==='number'?Number(val):val));}}/>;
 return <div className="p08-field"><label htmlFor={id}>{field.label||field.key}{field.required?' *':''}</label>{control}{field.help&&<small>{field.help}</small>}{error&&<small role="alert" className="p08-error">{error}</small>}</div>;
}
const defaultLora=opt=>({id:opt.id,version:opt.version,enabled:true,model_strength:1,clip_strength:1,order:0});
function LoraSettings({options,items,onChange}){
 const available=options||[];function change(id,key,value){onChange(items.map(x=>x.id===id?{...x,[key]:value}:x));}
 function shift(index,direction){const next=[...items];const other=index+direction;if(other<0||other>=next.length)return;[next[index],next[other]]=[next[other],next[index]];onChange(next.map((x,i)=>({...x,order:i})));}
 return <section className="p08-panel"><h3>LoRA</h3><p>فقط LoRAهایی که سازگاری آنها در Backend تأیید شده قابل انتخاب‌اند. خاموش کردن، وزن را حفظ می‌کند.</p>
 <label>افزودن LoRA <select value="" onChange={e=>{const item=available.find(x=>x.id===e.target.value);if(item&&!items.some(x=>x.id===item.id))onChange([...items,{...defaultLora(item),model_strength:Math.min(item.max_strength,Math.max(item.min_strength,1)),clip_strength:Math.min(item.max_strength,Math.max(item.min_strength,1)),order:items.length}]);}}><option value="">یک LoRA انتخاب کنید</option>{available.filter(x=>!items.some(s=>s.id===x.id)).map(x=><option key={x.id} value={x.id}>{x.name} · {x.version}</option>)}</select></label>
 <div className="p08-loras">{items.map((l,i)=>{const info=available.find(x=>x.id===l.id);return <article key={l.id} className="p08-lora"><strong>{info?.name||'LoRA unavailable'} · {l.version}</strong><label><input type="checkbox" checked={l.enabled} onChange={e=>change(l.id,'enabled',e.target.checked)}/>فعال</label><label>Model strength <input type="number" min={info?.min_strength} max={info?.max_strength} step="0.05" value={l.model_strength} onChange={e=>change(l.id,'model_strength',Number(e.target.value))}/></label><label>CLIP strength <input type="number" min={info?.min_strength} max={info?.max_strength} step="0.05" value={l.clip_strength} onChange={e=>change(l.id,'clip_strength',Number(e.target.value))}/></label><div><button type="button" onClick={()=>shift(i,-1)} disabled={i===0} aria-label="بالا">↑</button><button type="button" onClick={()=>shift(i,1)} disabled={i===items.length-1} aria-label="پایین">↓</button><button type="button" onClick={()=>onChange(items.filter(x=>x.id!==l.id).map((x,i)=>({...x,order:i})))}>حذف</button></div></article>})}</div>
 </section>;
}

export function ParameterStudio(){
 const {session,epoch,mutationToken}=useAuth();const search=useMemo(()=>new URLSearchParams(window.location.search),[epoch]);
 const models=usePrivate('/api/catalog/models');const [model,setModel]=useState(search.get('model')||'');const workflows=usePrivate(model?`/api/models/${encodeURIComponent(model)}/parameter-schemas`:null);
 const [workflow,setWorkflow]=useState(search.get('workflow')||'');const chosenPreset=search.get('preset');const preset=usePrivate(chosenPreset&&/^[A-Za-z0-9_-]{1,96}$/.test(chosenPreset)?'/api/presets/'+chosenPreset:null);const schema=usePrivate(model&&workflow?`/api/models/${encodeURIComponent(model)}/parameter-schema?workflow_id=${encodeURIComponent(workflow)}`:null);
 const loras=usePrivate(model?`/api/models/${encodeURIComponent(model)}/loras`:null);
 const [form,setForm]=useState({}),[selected,setSelected]=useState([]),[seedMode,setSeedMode]=useState('random'),[batchCount,setBatchCount]=useState(1),[batchMode,setBatchMode]=useState('SAME');
 const [modified,setModified]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[fieldError,setFieldError]=useState(''),[result,setResult]=useState(null),[presetName,setPresetName]=useState('');
 const last=useRef('');const pending=useRef(null);
 useEffect(()=>{setForm({});setSelected([]);setResult(null);pending.current=null;last.current='';},[session.user?.id,epoch]);
 useEffect(()=>{const key=schema.data?.schema_hash||'';if(key&&last.current!==key){last.current=key;setForm(fieldDefaults(schema.data.schema));setSelected([]);setModified(false);setResult(null);}},[schema.data?.schema_hash]);
 function setNextModel(next){if(modified&&!window.confirm('با تغییر مدل، مقادیر ناسازگار فرم فعلی کنار گذاشته می‌شوند. ادامه می‌دهید؟'))return;pending.current=null;setModel(next);setWorkflow('');setForm({});setSelected([]);setResult(null);setModified(false);}
 function setNextWorkflow(next){if(modified&&!window.confirm('با تغییر Workflow، تنظیمات فعلی کنار گذاشته شوند؟'))return;pending.current=null;setWorkflow(next);setForm({});setSelected([]);setResult(null);setModified(false);}
 function update(key,value){setForm(f=>({...f,[key]:value}));setModified(true);setResult(null);pending.current=null;}
 const fields=safeFields(schema.data?.schema);
 async function saveIntent(e){e.preventDefault();setBusy(true);setError('');setFieldError('');setResult(null);
  try{if(!schema.data)throw Error('Schema معتبر انتخاب نشده است.');if(seedMode==='fixed'){
   for(const f of fields.filter(f=>f.type==='seed'))if(!seedDecimal(form[f.key]))throw Error('Seed باید رشته عددی معتبر ۶۴‌بیتی باشد.');}
   const payload={client_request_id:pending.current?.id||uuid(),model_version_id:model,workflow_id:workflow,schema_hash:schema.data.schema_hash,
    parameters:removeUnsupported(form,schema.data.schema),seed_mode:seedMode,batch_count:batchCount,batch_mode:batchMode,loras:selected};
   if(seedMode!=='fixed')for(const f of fields.filter(f=>f.type==='seed'))delete payload.parameters[f.key];
   pending.current={id:payload.client_request_id};const csrfToken=await mutationToken();const response=await parametersRequest('/api/parameter-intents',{method:'POST',body:payload,csrfToken});pending.current=null;setResult(response);
  }catch(e){if(e.status&&e.status<500)pending.current=null;setError(e.message);setFieldError(e.fieldPath||'');}finally{setBusy(false);}}
 async function applyChosenPreset(){setBusy(true);setError('');try{
  const item=preset.data;
  if(!item||!schema.data||item.model_version_id!==model||item.workflow_id!==workflow)throw Error('Preset برای مدل یا Workflow انتخابی نیست.');
  const args=new URLSearchParams({model_version_id:model,workflow_id:workflow});
  await parametersRequest(`/api/presets/${encodeURIComponent(item.id)}/preview?${args}`);
  if(!window.confirm('تنظیمات Preset جایگزین مقادیر فعلی فرم شوند؟'))return;
  setForm({...fieldDefaults(schema.data.schema),...removeUnsupported(item.values,schema.data.schema)});
  setSelected(item.loras||[]);setResult(null);pending.current=null;setModified(true);
 }catch(e){setError(e.message);}finally{setBusy(false);}}
 async function savePreset(){setBusy(true);setError('');try{if(!schema.data||!presetName.trim())throw Error('نام Preset و Schema لازم است.');
  const subset=Object.fromEntries(Object.entries(removeUnsupported(form,schema.data.schema)).filter(([k])=>!k.toLowerCase().includes('prompt')));
  const csrfToken=await mutationToken();await parametersRequest('/api/presets',{method:'POST',csrfToken,body:{name:presetName,model_version_id:model,workflow_id:workflow,schema_hash:schema.data.schema_hash,values:subset,loras:selected,includes_prompt:false}});setPresetName('');setError('');window.alert('Preset خصوصی ذخیره شد.');
 }catch(e){setError(e.message);}finally{setBusy(false);}}
 return <section className="p08-page"><h1>تنظیمات هوشمند مدل</h1><p>فرم از Schema معتبر Backend ساخته می‌شود. ثبت تنظیمات، به معنی شروع Job یا مصرف GPU نیست.</p>
 {chosenPreset&&<State source={preset}>{item=>item?<div className="p08-panel"><p>Preset انتخابی: <strong>{item.name}</strong></p><button type="button" disabled={busy||!schema.data} onClick={applyChosenPreset}>بررسی و اعمال این Preset با تأیید من</button></div>:<p role="alert">Preset معتبر یافت نشد.</p>}</State>}
 <State source={models}>{data=><div className="p08-field"><label htmlFor="p08-model">مدل</label><select id="p08-model" value={model} onChange={e=>setNextModel(e.target.value)}><option value="">انتخاب مدل تأییدشده</option>{(data?.items||[]).map(m=><option value={m.id} key={m.id}>{m.name} · {m.revision}</option>)}</select>{!data?.items?.length&&<p>هنوز مدل تأییدشده وجود ندارد.</p>}</div>}</State>
 {model&&<State source={workflows}>{data=><div className="p08-field"><label htmlFor="p08-workflow">Workflow</label><select id="p08-workflow" value={workflow} onChange={e=>setNextWorkflow(e.target.value)}><option value="">نسخه سازگار</option>{(data?.items||[]).map(w=><option value={w.workflow_id} key={w.schema_id}>{w.workflow_id} · {w.schema_hash.slice(0,8)}</option>)}</select>{!data?.items?.length&&<p>Schema منتشرشده برای این مدل وجود ندارد.</p>}</div>}</State>}
 {model&&workflow&&<State source={schema}>{d=><form onSubmit={saveIntent} className="p08-form">
 <p className="p08-hint">Schema: <code dir="ltr">{d?.schema_hash.slice(0,12)}</code> · Revision: {d?.schema?.schema_version}</p>
 <div className="p08-fields">{fields.filter(f=>f.type!=='seed'||seedMode==='fixed').map(f=><DynamicField key={f.key} field={f} value={form[f.key]} onChange={v=>update(f.key,v)} error={fieldError==='parameters.'+f.key?'این مقدار برای مدل پشتیبانی نمی‌شود.':null}/>)}</div>
 {fields.some(f=>f.type==='seed')&&<div className="p08-panel"><h3>Seed</h3><label htmlFor="p08-seed-mode">روش انتخاب</label><select id="p08-seed-mode" value={seedMode} onChange={e=>{setSeedMode(e.target.value);setModified(true)}}><option value="random">تصادفی سمت سرور</option><option value="fixed">ثابت با مقدار ۶۴‌بیتی</option></select><p>Retry واقعی همان Snapshot را نگه می‌دارد؛ Generate چندکاربره فعلاً فعال نیست.</p></div>}
 <div className="p08-panel"><label htmlFor="p08-batch-count">تعداد خروجی</label><input id="p08-batch-count" type="number" min="1" max="8" value={batchCount} onChange={e=>setBatchCount(Number(e.target.value))}/><label htmlFor="p08-batch-mode">Seed خروجی‌ها</label><select id="p08-batch-mode" value={batchMode} onChange={e=>setBatchMode(e.target.value)}><option value="SAME">همه یک Seed</option><option value="INCREMENT">افزایشی</option><option value="INDEPENDENT_RANDOM">تصادفی مستقل</option></select></div>
 <State source={loras}>{data=><LoraSettings options={data?.items||[]} items={selected} onChange={arr=>{setSelected(arr);setModified(true);}}/>}</State>
 <button type="submit" disabled={busy}>{busy?'در حال اعتبارسنجی…':'اعتبارسنجی و ثبت Snapshot غیر اجرایی'}</button><button type="button" disabled title="اجرای Job تا تکمیل Gate مالکیت و Worker مسدود است">Generate (فعلاً غیرفعال)</button>
 {error&&<p role="alert" className="p08-error">{error}</p>}{result&&<div role="status" className="p08-success"><p>تنظیمات اعتبارسنجی شدند؛ هیچ Job جدیدی ساخته نشده است.</p><p>Seed نهایی: <code dir="ltr">{result.snapshot?.seeds_per_output?.join(', ')||'—'}</code></p></div>}
 </form>}</State>}
 {schema.data&&<section className="p08-panel"><h2>ذخیره Preset</h2><label htmlFor="p08-preset-name">نام تنظیمات</label><input id="p08-preset-name" value={presetName} onChange={e=>setPresetName(e.target.value)} maxLength={120}/><button type="button" disabled={busy||!presetName.trim()} onClick={savePreset}>ذخیره تنظیمات بدون Prompt</button><AppLink to="/presets">مدیریت Presetها</AppLink></section>}
 </section>;
}

export function PresetsPage(){const {session,mutationToken,epoch}=useAuth(),data=usePrivate('/api/presets');const [error,setError]=useState(''),[busy,setBusy]=useState(false),[preview,setPreview]=useState(null);
 async function rename(p){const name=window.prompt('نام جدید Preset',p.name);if(name===null)return;if(!name.trim())return;setBusy(true);setError('');try{await parametersRequest('/api/presets/'+encodeURIComponent(p.id),{method:'PATCH',csrfToken:await mutationToken(),body:{name:name.trim()}});data.retry();}catch(e){setError(e.message)}finally{setBusy(false)}}
 async function discard(id){if(!window.confirm('این Preset فقط از فهرست شخصی شما حذف شود؟'))return;setBusy(true);setError('');try{await parametersRequest('/api/presets/'+encodeURIComponent(id),{method:'DELETE',csrfToken:await mutationToken()});data.retry();}catch(e){setError(e.message)}finally{setBusy(false)}}
 async function showPreview(p){setPreview(null);setError('');try{const args=new URLSearchParams({model_version_id:p.model_version_id,workflow_id:p.workflow_id});const result=await parametersRequest(`/api/presets/${encodeURIComponent(p.id)}/preview?${args}`);setPreview({...result,name:p.name,model_version_id:p.model_version_id,workflow_id:p.workflow_id});}catch(e){setError(e.message)}}
 return <section className="p08-page"><h1>Presetهای خصوصی</h1><p>تنظیمات تنها برای حساب فعلی ذخیره می‌شوند. ناسازگاری Schema قبل از استفاده بررسی می‌شود.</p><State source={data}>{d=><>{!d.items?.length&&<p>هنوز Preset ندارید. <AppLink to="/create/image">ساخت یک تنظیمات</AppLink></p>}<div className="p08-grid">{d.items?.map(p=><article className="p08-card" key={p.id}><h2>{p.name}</h2><p>مدل: <code dir="ltr">{p.model_version_id.slice(0,8)}</code> · {Object.keys(p.values).length} مقدار</p><button type="button" onClick={()=>showPreview(p)}>بررسی سازگاری و تغییرات</button><button type="button" disabled={busy} onClick={()=>rename(p)}>تغییر نام</button><button type="button" disabled={busy} onClick={()=>discard(p.id)}>حذف</button></article>)}</div></>}</State>
 {preview&&<div className="p08-panel" role="status"><h2>{preview.name}</h2><p>این Preset سازگار است؛ اعمال آن نیازمند تأیید کاربر است.</p><pre dir="ltr">{JSON.stringify({parameters:preview.changes,loras:preview.loras},null,2)}</pre><AppLink to={'/create/image?'+new URLSearchParams({model:preview.model_version_id||'',workflow:preview.workflow_id||'',preset:preview.preset_id})}>رفتن به فرم برای اعمال با تأیید</AppLink></div>}{error&&<p role="alert" className="p08-error">{error}</p>}</section>;
}
