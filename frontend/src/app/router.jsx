import React,{lazy,Suspense,useEffect,useState} from 'react';
import {AuthProvider,useAuth} from '../auth/session.jsx';
import {routeFor,isAdmin,safeReturnTo} from '../auth/routeUtils.js';
import {subscribeLocation,navigate} from './navigation.js';
import {LoginPage,RegisterPage,VerifyPage,ForgotPage,ResetPage,TwoFactorPage} from '../auth/AuthPages.jsx';
import {UserLayout,AdminLayout,AuthLayout,AppLink} from '../layouts/Layouts.jsx';
import {Dashboard,JobsPage,JobDetails,LibraryPage,CreateImagePage,AccountSecurityPage,UnsupportedPage,AdminPage} from '../pages/UserPages.jsx';

// Legacy Controller remains untouched and is the DEFAULT until an operator explicitly opts in.
const LegacyApp=lazy(()=>import('../App.jsx'));
const ENABLED=import.meta.env.VITE_AUTH_UI_ENABLED==='true';
const AuthPageMap={'/login':LoginPage,'/register':RegisterPage,'/verify-email':VerifyPage,'/forgot-password':ForgotPage,'/reset-password':ResetPage,'/auth/2fa':TwoFactorPage};

function Redirect({to}) { useEffect(()=>navigate(to,{replace:true}),[to]);return <div className="p04-root p04-wait" role="status">در حال تغییر مسیر…</div>; }
function Page(){
  const [path,setPath]=useState(()=>window.location.pathname),{session}=useAuth();
  useEffect(()=>subscribeLocation(()=>{setPath(window.location.pathname);window.scrollTo(0,0);}),[]);
  const route=routeFor(path);
  if(route.scope==='redirect')return <Redirect to={route.to}/>;
  if(session.state==='unknown')return <div className="p04-root p04-wait" role="status">در حال بررسی نشست امن…</div>;
  if(session.state==='unavailable')return <AuthLayout title="سرویس فعلاً در دسترس نیست"><p role="alert" className="p04-alert">به علت خطای ارتباط یا نبود Migration، وضعیت ورود تأیید نشد. هیچ داده خصوصی نمایش داده نمی‌شود.</p><button type="button" onClick={()=>window.location.reload()}>تلاش دوباره</button></AuthLayout>;
  if(route.scope==='public'){
    const Component=AuthPageMap[route.path];
    if(session.state==='authenticated'&&['/login','/register'].includes(route.path)) return <Redirect to="/dashboard"/>;
    return <Component/>;
  }
  if(route.scope==='missing')return <AuthLayout title="صفحه پیدا نشد"><AppLink to="/dashboard">بازگشت به خانه</AppLink></AuthLayout>;
  if(session.state!=='authenticated'){
    const returnTo=route.scope==='user'?safeReturnTo(window.location.pathname+window.location.search):'/dashboard';
    return <Redirect to={`/login?returnTo=${encodeURIComponent(returnTo)}`}/>;
  }
  if(route.scope==='admin'&&!isAdmin(session.user))return <UserLayout title="عدم دسترسی"><section className="p04-alert" role="alert"><h1>۴۰۳ — مجوز ندارید</h1><p>این بخش مخصوص مدیران است.</p><AppLink to="/dashboard">بازگشت</AppLink></section></UserLayout>;
  if(route.scope==='admin')return <AdminLayout title="مدیریت"><AdminPage/></AdminLayout>;
  let title='داشبورد',node=<Dashboard/>;
  if(route.path==='/jobs'){title='کارهای من';node=<JobsPage/>;}
  else if(route.path.startsWith('/jobs/')){title='جزئیات کار';node=<JobDetails selectedId={route.path.split('/')[2]}/>;}
  else if(route.path==='/library'){title='کتابخانه';node=<LibraryPage/>;}
  else if(route.path==='/create/image'||route.path==='/edit/image'){title='ساخت و ویرایش';node=<CreateImagePage/>;}
  else if(route.path==='/account/security'){title='امنیت حساب';node=<AccountSecurityPage/>;}
  else if(route.path!=='/dashboard'){title='بخش در حال توسعه';node=<UnsupportedPage/>;}
  return <UserLayout title={title}>{node}</UserLayout>;
}
export function Phase04App(){return ENABLED?<AuthProvider><Page/></AuthProvider>:<Suspense fallback={<p role="status">در حال بارگذاری Controller…</p>}><LegacyApp/></Suspense>;}
