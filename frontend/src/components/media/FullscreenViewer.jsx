import React,{useEffect,useRef,useState} from 'react';
import {privateMediaBlob} from '../../pages/library/mediaClient.js';

export function FullscreenViewer({assets,id,onClose,onMove,onDownload,onReuse,ownerClient,epoch}){
 const [source,setSource]=useState(null),[state,setState]=useState('loading'),[zoom,setZoom]=useState(1),[pan,setPan]=useState({x:0,y:0});
 const [compare,setCompare]=useState(false),[split,setSplit]=useState(50),[compareSource,setCompareSource]=useState(null);
 const closeRef=useRef(null),dialog=useRef(null),touchX=useRef(null),objectUrls=useRef([]),imageRef=useRef(null);
 const item=assets.find(x=>x.asset_id===id),other=assets.find(x=>x.asset_id!==id && x.mime_type?.startsWith('image/'));
 useEffect(()=>{
  const old=document.activeElement;const overflow=document.body.style.overflow;document.body.style.overflow='hidden';closeRef.current?.focus();
  return()=>{document.body.style.overflow=overflow;old?.focus?.();};
 },[]);
 useEffect(()=>{
  let active=true;const ctrl=new AbortController();setState('loading');setSource(null);setZoom(1);setPan({x:0,y:0});
  privateMediaBlob(ownerClient,id,'preview',ctrl.signal).then(blob=>{
   if(!active)return;const url=URL.createObjectURL(blob);objectUrls.current.push(url);ownerClient.registerObjectUrl(url);setSource(url);setState('ready');
  }).catch(e=>{if(active&&!ctrl.signal.aborted)setState('error');});
  return()=>{active=false;ctrl.abort();};
 },[id,epoch,ownerClient]);
 useEffect(()=>{
  let active=true,ctrl=new AbortController();setCompareSource(null);
  if(compare&&other)privateMediaBlob(ownerClient,other.asset_id,'preview',ctrl.signal).then(blob=>{
   if(!active)return;const url=URL.createObjectURL(blob);objectUrls.current.push(url);ownerClient.registerObjectUrl(url);setCompareSource(url);
  }).catch(()=>{if(active)setCompare(false)});
  return()=>{active=false;ctrl.abort();};
 },[compare,other?.asset_id,epoch,ownerClient]);
 useEffect(()=>()=>{objectUrls.current.forEach(url=>URL.revokeObjectURL(url));objectUrls.current=[];},[]);
 useEffect(()=>{
  const key=e=>{
   if(e.key==='Escape'){e.preventDefault();onClose();}
   if(e.key==='ArrowLeft'){e.preventDefault();onMove(-1);}
   if(e.key==='ArrowRight'){e.preventDefault();onMove(1);}
   if(e.key==='Tab'){
    const candidates=[...dialog.current.querySelectorAll('button:not([disabled]),input:not([disabled]),a[href]')];
    if(!candidates.length)return;const first=candidates[0],last=candidates.at(-1);
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
    else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
   }
  };
  document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key);
 },[onClose,onMove]);
 const video=item?.mime_type?.startsWith('video/');
 return <div className="p06-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}>
  <section ref={dialog} role="dialog" aria-modal="true" aria-label="نمایش تمام‌صفحه رسانه" className="p06-viewer" dir="rtl">
   <header className="p06-viewerbar"><strong>نمایش خصوصی</strong><div className="p06-actions">
    <button ref={closeRef} type="button" onClick={onClose} aria-label="بستن نمایشگر">× بستن</button>
    <button type="button" onClick={()=>onMove(-1)} disabled={assets.length<2}>قبلی</button>
    <button type="button" onClick={()=>onMove(1)} disabled={assets.length<2}>بعدی</button>
    {!video&&<><button type="button" onClick={()=>{setZoom(1);setPan({x:0,y:0})}}>Fit</button><button type="button" onClick={()=>{const i=imageRef.current,container=dialog.current?.querySelector('.p06-image-stage');if(!i||!container)return;const ratio=Math.min(container.clientWidth/i.naturalWidth,container.clientHeight/i.naturalHeight);if(ratio>0)setZoom(Math.min(8,Math.max(.5,1/ratio)));}}>۱:۱</button><button type="button" onClick={()=>setZoom(v=>Math.min(8,v+.25))}>＋</button><button type="button" onClick={()=>setZoom(v=>Math.max(.5,v-.25))}>－</button></>}
    <button type="button" onClick={()=>onDownload(item)} disabled={!item}>دانلود اصلی</button>
    <button type="button" onClick={()=>onReuse(item)} disabled={!item}>استفاده به‌عنوان مرجع</button>
    {!video&&other&&<button type="button" onClick={()=>setCompare(x=>!x)}>مقایسه</button>}
   </div></header>
   <div className="p06-stage" onTouchStart={e=>{touchX.current=e.changedTouches[0]?.clientX}}
    onTouchEnd={e=>{if(touchX.current==null)return;const d=e.changedTouches[0]?.clientX-touchX.current;if(Math.abs(d)>70)onMove(d>0?-1:1);touchX.current=null}}
    onWheel={e=>{if(!video&&e.ctrlKey){e.preventDefault();setZoom(v=>Math.min(8,Math.max(.5,v+(e.deltaY<0?.1:-.1))))}}}>
    {state==='loading'&&<p role="status">در حال دریافت فایل با مجوز حساب…</p>}
    {state==='error'&&<div role="alert">امکان نمایش وجود ندارد. لینک خصوصی ممکن است منقضی شده باشد.<button type="button" onClick={()=>onMove(0)}>تلاش دوباره</button></div>}
    {state==='ready'&&source&&(video?<video src={source} controls playsInline preload="metadata" autoPlay={false}/>:
      <div className="p06-image-stage" onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);e.currentTarget.dataset.lastX=String(e.clientX);e.currentTarget.dataset.lastY=String(e.clientY)}}
       onPointerMove={e=>{if(!e.currentTarget.hasPointerCapture(e.pointerId)||zoom===1)return;const x=Number(e.currentTarget.dataset.lastX),y=Number(e.currentTarget.dataset.lastY);setPan(p=>({x:p.x+e.clientX-x,y:p.y+e.clientY-y}));e.currentTarget.dataset.lastX=String(e.clientX);e.currentTarget.dataset.lastY=String(e.clientY)}}
       onPointerUp={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId)}}>
       <img ref={imageRef} src={source} alt="تصویر اصلی" style={{transform:`translate(${pan.x}px,${pan.y}px) scale(${zoom})`}} draggable="false"/>
       {compare&&compareSource&&<div className="p06-compare" style={{width:split+'%'}}><img src={compareSource} alt="تصویر مقایسه" draggable="false"/></div>}
      </div>)}
   </div>
   {compare&&<label className="p06-split">موقعیت مقایسه <input type="range" min="0" max="100" value={split} onChange={e=>setSplit(+e.target.value)}/></label>}
   <footer className="p06-viewerfoot"><span>{item?.width&&item?.height?`${item.width} × ${item.height}`:item?.mime_type||'رسانه'}</span><span>ESC بستن · جهت‌نما جابه‌جایی</span></footer>
  </section>
 </div>;
}
