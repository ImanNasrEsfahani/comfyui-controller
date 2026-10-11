import React,{useEffect,useMemo,useState} from 'react';
import {authRequest, ApiError, messageForStatus} from './api.js';
import {useAuth} from './session.jsx';
import {safeReturnTo,maskedEmail} from './routeUtils.js';
import {navigate} from '../app/navigation.js';
import {AppLink,AuthLayout} from '../layouts/Layouts.jsx';

function Field({name,label,type='text',value,onChange,autoComplete,required=true,minLength,maxLength,dir}){
  const [visible,setVisible]=useState(false);const isPassword=type==='password';
  return <div className="p04-field"><label htmlFor={name}>{label}</label><div className="p04-field-control"><input id={name} name={name} type={isPassword?(visible?'text':'password'):type} value={value} onChange={e=>onChange(e.target.value)} autoComplete={autoComplete} required={required} minLength={minLength} maxLength={maxLength} dir={dir||((type==='email'||isPassword)?'ltr':undefined)} aria-label={label}/>{isPassword&&<button type="button" className="p04-reveal" onClick={()=>setVisible(!visible)} aria-label={visible?'پنهان کردن رمز':'نمایش رمز'} aria-pressed={visible}>{visible?'پنهان':'نمایش'}</button>}</div></div>;
}
function Feedback({error,success}){return <>{error&&<p className="p04-alert" role="alert">{error}</p>}{success&&<p className="p04-success" role="status">{success}</p>}</>;}
function Submit({busy,children}){return <button type="submit" className="p04-action" disabled={busy}>{busy?'در حال پردازش…':children}</button>;}
function useForm(){const [busy,setBusy]=useState(false),[error,setError]=useState(''),[success,setSuccess]=useState('');
  async function submit(task){if(busy)return;setBusy(true);setError('');setSuccess('');try{await task(setSuccess);}catch(e){setError(e instanceof ApiError?messageForStatus(e.status):e.message||'خطای ارتباط با سرور');}finally{setBusy(false);}}
  return {busy,error,success,setError,submit};}
function PasswordHint({password}){let strength=password.length>=16?'مناسب':password.length>=12?'قابل قبول':'کوتاه';return <p className="p04-help" aria-live="polite">طول رمز: {password.length} کاراکتر · {strength} (حداقل ۱۲)</p>;}

export function LoginPage(){
  const auth=useAuth(),form=useForm();const [email,setEmail]=useState(''),[password,setPassword]=useState(''),[remember,setRemember]=useState(false);
  const dest=safeReturnTo(new URLSearchParams(window.location.search).get('returnTo'));
  return <AuthLayout title="خوش آمدید" subtitle="برای ادامه وارد حساب کاربری خود شوید."><form onSubmit={e=>{e.preventDefault();void form.submit(async()=>{await auth.login({email,password,remember_me:remember});navigate(dest,{replace:true});});}}>
    <Field name="email" label="ایمیل" type="email" value={email} onChange={setEmail} autoComplete="email"/>
    <Field name="password" label="رمز عبور" type="password" value={password} onChange={setPassword} autoComplete="current-password"/>
    <div className="p04-inline"><label className="p04-check"><input type="checkbox" checked={remember} onChange={e=>setRemember(e.target.checked)}/> مرا به خاطر بسپار</label><AppLink to="/forgot-password">فراموشی رمز؟</AppLink></div>
    <Feedback error={form.error}/><Submit busy={form.busy}>ورود</Submit>
  </form><p className="p04-bottom">حساب ندارید؟ <AppLink to="/register">ثبت‌نام کنید</AppLink></p></AuthLayout>;
}
export function RegisterPage(){
  const form=useForm();const [name,setName]=useState(''),[email,setEmail]=useState(''),[password,setPassword]=useState(''),[confirm,setConfirm]=useState(''),[invite,setInvite]=useState(''),[consent,setConsent]=useState(false);
  return <AuthLayout title="ایجاد حساب" subtitle="ثبت‌نام ممکن است به دعوت معتبر نیاز داشته باشد."><form onSubmit={e=>{e.preventDefault();if(password!==confirm){form.setError('تکرار رمز عبور یکسان نیست.');return;}void form.submit(async()=>{await authRequest('/register',{method:'POST',body:{display_name:name,email,password,invite_token:invite||null,terms_accepted:consent}});navigate('/verify-email',{replace:true});});}}>
    <Field name="display_name" label="نام کامل" value={name} onChange={setName} autoComplete="name" maxLength={150}/>
    <Field name="email" label="ایمیل" type="email" value={email} onChange={setEmail} autoComplete="email"/>
    <Field name="password" label="رمز عبور" type="password" value={password} onChange={setPassword} autoComplete="new-password" minLength={12}/><PasswordHint password={password}/>
    <Field name="confirm_password" label="تکرار رمز عبور" type="password" value={confirm} onChange={setConfirm} autoComplete="new-password" minLength={12}/>
    <Field name="invite" label="کد دعوت (در صورت داشتن)" value={invite} onChange={setInvite} required={false} dir="ltr"/>
    <label className="p04-check"><input type="checkbox" required checked={consent} onChange={e=>setConsent(e.target.checked)}/> شرایط استفاده و سیاست حریم خصوصی را می‌پذیرم.</label>
    <Feedback error={form.error}/><Submit busy={form.busy}>ایجاد حساب</Submit>
  </form><p className="p04-bottom">حساب دارید؟ <AppLink to="/login">ورود</AppLink></p></AuthLayout>;
}

// Read fragment token exactly once at module evaluation (React StrictMode may render twice).
// The secret remains only in module memory and is erased from the browser URL immediately.
const incomingLink = (() => {
  if (typeof window === 'undefined' || import.meta.env.VITE_AUTH_UI_ENABLED !== 'true') return {path:'',token:''};
  const token = new URLSearchParams(window.location.hash.replace(/^#/,'')).get('token') || '';
  const path = window.location.pathname;
  if (token) window.history.replaceState(window.history.state,'',path+window.location.search);
  return {path,token};
})();
function initialSecret(path){return incomingLink.path===path ? incomingLink.token : '';}
export function VerifyPage(){const form=useForm();const [token,setToken]=useState(()=>initialSecret('/verify-email'));const [email,setEmail]=useState('');const [cooldown,setCooldown]=useState(false);
  return <AuthLayout title="تأیید ایمیل" subtitle="لینک ارسال‌شده به ایمیل خود را باز کنید.">
    {token?<form onSubmit={e=>{e.preventDefault();void form.submit(async(setSuccess)=>{await authRequest('/verify-email',{method:'POST',body:{token}});setToken('');setSuccess('آدرس ایمیل تأیید شد. اکنون وارد شوید.');});}}><p className="p04-help">توکن تأیید در مرورگر دریافت شد.</p><Submit busy={form.busy}>تأیید ایمیل</Submit></form>:<p className="p04-help">اگر لینک تأیید ندارید، آدرس ایمیل خود را برای ارسال دوباره وارد کنید.</p>}
    {!token&&<form onSubmit={e=>{e.preventDefault();void form.submit(async(setSuccess)=>{await authRequest('/resend-verification',{method:'POST',body:{email}});setSuccess('در صورت واجد شرایط بودن حساب، ایمیل ارسال خواهد شد.');setCooldown(true);});}}><Field name="email" label="ایمیل" type="email" value={email} onChange={setEmail}/>{email&&<small className="p04-help">آدرس: {maskedEmail(email)}</small>}<button type="submit" disabled={form.busy||cooldown}>ارسال مجدد لینک</button></form>}
    <Feedback error={form.error} success={form.success}/><p className="p04-bottom"><AppLink to="/login">بازگشت به ورود</AppLink></p>
  </AuthLayout>;
}
export function ForgotPage(){const form=useForm(),[email,setEmail]=useState('');return <AuthLayout title="بازیابی رمز عبور" subtitle="اگر این ایمیل حساب معتبری داشته باشد، لینک بازیابی ارسال می‌شود."><form onSubmit={e=>{e.preventDefault();void form.submit(async(setSuccess)=>{await authRequest('/forgot-password',{method:'POST',body:{email}});setSuccess('اگر حساب واجد شرایطی وجود داشته باشد، ایمیل بازیابی ارسال می‌شود.');});}}><Field name="email" label="ایمیل" type="email" value={email} onChange={setEmail} autoComplete="email"/><Feedback error={form.error} success={form.success}/><Submit busy={form.busy}>ارسال لینک</Submit></form><p className="p04-bottom"><AppLink to="/login">بازگشت به ورود</AppLink></p></AuthLayout>;}
export function ResetPage(){const form=useForm();const [token,setToken]=useState(()=>initialSecret('/reset-password')),[password,setPassword]=useState(''),[confirm,setConfirm]=useState(''),[done,setDone]=useState(false);
 return <AuthLayout title="تعیین رمز جدید" subtitle="لینک بازیابی یک‌بارمصرف و محدود به زمان است.">{token&&!done?<form onSubmit={e=>{e.preventDefault();if(password!==confirm){form.setError('دو رمز یکسان نیستند.');return;}void form.submit(async()=>{await authRequest('/reset-password',{method:'POST',body:{token,new_password:password}});setToken('');setDone(true);});}}><Field name="password" label="رمز جدید" type="password" value={password} onChange={setPassword} minLength={12} autoComplete="new-password"/><PasswordHint password={password}/><Field name="confirm_password" label="تکرار رمز" type="password" value={confirm} onChange={setConfirm} minLength={12} autoComplete="new-password"/><Feedback error={form.error}/><Submit busy={form.busy}>ذخیره رمز جدید</Submit></form>:<p className="p04-help">{done?'رمز عبور تغییر کرد و نشست‌های قبلی باطل شدند.':'لینک معتبر یافت نشد یا قبلاً مصرف شده است.'}</p>}<p className="p04-bottom"><AppLink to={done?'/login':'/forgot-password'}>{done?'ورود به حساب':'درخواست لینک جدید'}</AppLink></p></AuthLayout>;
}
export function TwoFactorPage(){return <AuthLayout title="تأیید دومرحله‌ای" subtitle="احراز هویت دومرحله‌ای در انتظار فعال‌سازی Backend است."><p className="p04-alert" role="status">ورود دومرحله‌ای هنوز در این نسخه فعال نشده است. هیچ کد تأییدی در این صفحه پذیرفته نمی‌شود.</p><AppLink to="/login">بازگشت به ورود</AppLink></AuthLayout>;}
