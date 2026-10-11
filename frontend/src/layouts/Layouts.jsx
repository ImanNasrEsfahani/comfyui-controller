import React,{useEffect,useState} from 'react';
import {useAuth} from '../auth/session.jsx';
import {navigate} from '../app/navigation.js';
import {accountRequest} from '../pages/accountClient.js';

export function AppLink({to,children,className,...props}){
  return <a href={to} className={className} {...props} onClick={event=>{
    props.onClick?.(event);
    if(!event.defaultPrevented && event.button===0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey){event.preventDefault();navigate(to);}
  }}>{children}</a>;
}
export function PublicLayout({children}){
  return <div className="p04-root" dir="rtl"><header className="p04-publicbar"><AppLink to="/dashboard" className="p04-brand">COMFY <span>STUDIO</span></AppLink><nav aria-label="دسترسی عمومی"><AppLink to="/login">ورود</AppLink><AppLink to="/register">ثبت‌نام</AppLink></nav></header>{children}<footer className="p04-footer">ساخت و ویرایش تصویر با هوش مصنوعی · اطلاعات شخصی به‌صورت خصوصی نگهداری می‌شود.</footer></div>;
}
export function AuthLayout({title,subtitle,children}){
  return <PublicLayout><main className="p04-auth-main"><section className="p04-auth-card" aria-labelledby="auth-heading"><div className="p04-mark" aria-hidden="true">✦</div><h1 id="auth-heading">{title}</h1>{subtitle&&<p className="p04-subtitle">{subtitle}</p>}{children}</section></main></PublicLayout>;
}
export function UserLayout({children,title='داشبورد'}){
  const {session,logout,epoch}=useAuth();const [preferences,setPreferences]=useState({locale:'fa',theme:'system'});const [menu,setMenu]=useState(false);const [pending,setPending]=useState(false);const [error,setError]=useState('');
  useEffect(()=>{
    const controller=new AbortController();
    async function sync(){try{const value=await accountRequest('/api/users/me/preferences',{signal:controller.signal});
      if(!controller.signal.aborted)setPreferences({locale:value.locale||'fa',theme:value.theme||'system'});
    }catch{/* Missing Phase05 migration or account feature flag: stay on safe defaults. */}}
    void sync();window.addEventListener('comfyui:preferences-updated',sync);
    return()=>{controller.abort();window.removeEventListener('comfyui:preferences-updated',sync);};
  },[epoch,session.user?.id]);
  useEffect(()=>{
    const html=document.documentElement;
    html.dataset.p05Theme=preferences.theme;
    html.lang=preferences.locale;
    return()=>{delete html.dataset.p05Theme;html.lang='fa';};
  },[preferences.theme,preferences.locale]);
  const nav=[['/dashboard','داشبورد'],['/create/image','ساخت تصویر'],['/edit/image','ویرایش تصویر'],['/create/video','ساخت ویدئو'],['/edit/video','ویرایش ویدئو'],['/jobs','کارهای من'],['/library','کتابخانه'],['/tools','مدل‌ها'],['/presets','Presetهای من'],['/usage','مصرف GPU'],['/workflows','Workflow Studio'],['/account/profile','پروفایل'],['/account/security','امنیت حساب'],['/account/preferences','ترجیحات'],['/account/data','حریم خصوصی'],...(session.user?.roles?.some(x=>x==='admin'||x==='superadmin')?[['/admin','مدیریت'],['/admin/models','مدل‌ها'],['/admin/worker-images','Worker Images'],['/admin/deployment-profiles','Deployment Profiles'],['/admin/infrastructure','زیرساخت GPU']]:[])];
  async function exit(){setPending(true);setError('');try{await logout();navigate('/login',{replace:true});}catch(err){setError('خروج در سرور تأیید نشد؛ نشست را از دستگاه‌های دیگر نیز باطل کنید.');}finally{setPending(false);}}
  return <div className="p04-root p04-shell" dir={preferences.locale==='en'?'ltr':'rtl'}><aside className={'p04-sidebar '+(menu?'p04-open':'')} aria-label="ناوبری کاربر"><AppLink to="/dashboard" className="p04-brand" onClick={()=>setMenu(false)}>COMFY <span>STUDIO</span></AppLink><nav aria-label="بخش‌های برنامه">{nav.map(([to,label])=><AppLink key={to} to={to} className={location.pathname===to?'p04-selected':''} onClick={()=>setMenu(false)}>{label}</AppLink>)}</nav></aside>{menu&&<button className="p04-overlay" type="button" onClick={()=>setMenu(false)} aria-label="بستن منو"/>}<div className="p04-content"><header className="p04-shell-top"><button type="button" className="p04-menu" aria-label="نمایش منو" aria-expanded={menu} onClick={()=>setMenu(!menu)}>☰</button><div><small>فضای شخصی</small><strong>{title}</strong></div><div className="p04-account"><span title={session.user?.email}>{session.user?.display_name || 'کاربر'}</span><button type="button" onClick={exit} disabled={pending}>خروج</button></div></header>{error&&<p role="alert" className="p04-alert">{error}</p>}<main className="p04-page">{children}</main></div></div>;
}
export function AdminLayout({children,title='مدیریت'}){
  return <UserLayout title={title}><div className="p04-admin-notice" role="status">بخش مدیریت فقط با نقش معتبر نمایش داده می‌شود. دسترسی مدیریتی به محتوای خصوصی کاربران بدون مجوز و Audit فعال نیست.</div>{children}</UserLayout>;
}
export function FullscreenMediaLayout({children}){return <div className="p04-fullscreen" dir="rtl">{children}</div>;}
