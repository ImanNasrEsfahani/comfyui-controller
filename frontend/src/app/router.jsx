import React,{lazy,Suspense,useEffect,useState} from 'react';
import {AuthProvider,useAuth} from '../auth/session.jsx';
import {routeFor,isAdmin,safeReturnTo} from '../auth/routeUtils.js';
import {subscribeLocation,navigate} from './navigation.js';
import {LoginPage,RegisterPage,VerifyPage,ForgotPage,ResetPage,TwoFactorPage} from '../auth/AuthPages.jsx';
import {UserLayout,AdminLayout,AuthLayout,AppLink} from '../layouts/Layouts.jsx';
import {JobsPage,JobDetails,LibraryPage,CreateImagePage,AccountSecurityPage,UnsupportedPage} from '../pages/UserPages.jsx';
import {PersonalDashboard,ProfilePage,PreferencesPage,DataPage,AccountSecurityExtras} from '../pages/Phase05Pages.jsx';
import {AdminOverview,AdminUsers,AdminUserDetail,AdminAudit} from '../pages/Phase05Admin.jsx';
import {PrivateLibrary,PrivateAssetDetail,ReferenceDraftPanel} from '../pages/library/PrivateLibrary.jsx';
import {Phase06JobDetails} from '../pages/library/Phase06Jobs.jsx';
import {ParameterStudio,PresetsPage} from '../pages/parameters/ParameterPages.jsx';
import {ToolsCatalog,ModelDetails,AdminModels,AdminWorkerImages,AdminDeploymentProfiles} from '../pages/registry/RegistryPages.jsx';
import {WorkflowStudio,WorkflowList,WorkflowVersions} from '../pages/workflows/WorkflowPages.jsx';
import {StudioEditor,StudioVersions} from '../pages/workflows/StudioV2.jsx';
import {UsagePage,InfrastructurePage} from '../pages/scheduling/SchedulingPages.jsx';

// Legacy Controller remains untouched and is the DEFAULT until an operator explicitly opts in.
const LegacyApp=lazy(()=>import('../App.jsx'));
const ENABLED=import.meta.env.VITE_AUTH_UI_ENABLED==='true';
const STUDIO_ENABLED=import.meta.env.VITE_WORKFLOW_STUDIO_ENABLED==='true';
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
  if(route.scope==='admin'){
    let adminNode=<AdminOverview/>,adminTitle='مدیریت';
    if(route.path==='/admin/users'){adminTitle='کاربران';adminNode=<AdminUsers/>;}
    else if(route.path.startsWith('/admin/users/')){adminTitle='جزئیات کاربر';adminNode=<AdminUserDetail id={route.path.split('/')[3]}/>;}
    else if(route.path==='/admin/audit-logs'){adminTitle='لاگ حسابرسی';adminNode=<AdminAudit/>;}
    else if(route.path==='/admin/infrastructure'){adminTitle='زیرساخت GPU';adminNode=<InfrastructurePage/>;}
    else if(route.path==='/admin/models'){adminTitle='مدل‌ها';adminNode=<AdminModels/>;}
    else if(route.path==='/admin/worker-images'){adminTitle='Worker Images';adminNode=<AdminWorkerImages/>;}
    else if(route.path==='/admin/deployment-profiles'){adminTitle='Deployment Profiles';adminNode=<AdminDeploymentProfiles/>;}
    else if(route.path!=='/admin')adminNode=<UnsupportedPage title="ابزار مدیریت"/>;
    return <AdminLayout title={adminTitle}>{adminNode}</AdminLayout>;
  }
  let title='داشبورد',node=<PersonalDashboard/>;
  if(route.path==='/workflows/new'){title='Workflow Studio';node=STUDIO_ENABLED?<StudioEditor/>:<WorkflowStudio/>;}
  else if(route.path==='/workflows'){title='Workflowهای من';node=<WorkflowList/>;}
  else if(/^\/workflows\/[^/]+\/edit\/[^/]+$/.test(route.path)){title='ویرایش Workflow';node=STUDIO_ENABLED?<StudioEditor definitionId={route.path.split('/')[2]} versionId={route.path.split('/')[4]}/>:<UnsupportedPage title="Studio Graph UI غیرفعال است"/>;}
  else if(route.path.startsWith('/workflows/')){title='نسخه‌های Workflow';node=STUDIO_ENABLED?<StudioVersions id={route.path.split('/')[2]}/>:<WorkflowVersions id={route.path.split('/')[2]}/>;}
  else if(route.path==='/usage'){title='مصرف و سهمیه';node=<UsagePage/>;}
  else if(route.path==='/tools'){title='کاتالوگ';node=<ToolsCatalog/>;}
  else if(route.path.startsWith('/models/')){title='مدل';node=<ModelDetails id={route.path.split('/')[2]}/>;}
  else if(route.path==='/presets'){title='Presetهای من';node=<PresetsPage/>;}
  else if(route.path==='/jobs'){title='کارهای من';node=<JobsPage/>;}
  else if(route.path.startsWith('/jobs/')){title='جزئیات کار';node=<Phase06JobDetails id={route.path.split('/')[2]}/>;}
  else if(route.path==='/library'){title='کتابخانه';node=<PrivateLibrary/>;}
  else if(route.path.startsWith('/library/')){title='جزئیات فایل';node=<PrivateAssetDetail id={route.path.split('/')[2]}/>;}
  else if(route.path==='/create/image'||route.path==='/edit/image'){title='ساخت و ویرایش';node=<><ParameterStudio/><ReferenceDraftPanel/></>;}
  else if(route.path==='/account/security'){title='امنیت حساب';node=<><AccountSecurityPage/><AccountSecurityExtras/></>;}
  else if(route.path==='/account/profile'){title='پروفایل';node=<ProfilePage/>;}
  else if(route.path==='/account/preferences'){title='ترجیحات';node=<PreferencesPage/>;}
  else if(route.path==='/account/data'){title='داده و حریم خصوصی';node=<DataPage/>;}
  else if(route.path!=='/dashboard'){title='بخش در حال توسعه';node=<UnsupportedPage/>;}
  return <UserLayout title={title}>{node}</UserLayout>;
}
export function Phase04App(){return ENABLED?<AuthProvider><Page/></AuthProvider>:<Suspense fallback={<p role="status">در حال بارگذاری Controller…</p>}><LegacyApp/></Suspense>;}
