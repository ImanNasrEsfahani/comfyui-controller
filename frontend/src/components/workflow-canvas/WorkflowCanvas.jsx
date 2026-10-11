import React,{useCallback,useMemo,useRef} from 'react';
import {between,snap} from './graphEdit.mjs';

const W=188,H=106;
export function WorkflowCanvas({graph,layout,viewport,onViewport,onLayout,selected,onSelect,catalog}){
 const surface=useRef(null),drag=useRef(null);
 const positions=useMemo(()=>Object.fromEntries(graph.nodes.map((n,i)=>[n.id,layout[n.id]||{x:snap(70+(i%4)*235),y:snap(70+Math.floor(i/4)*160)}])),[graph.nodes,layout]);
 const byId=useMemo(()=>new Map(graph.nodes.map(n=>[n.id,n])),[graph.nodes]);
 const typeMap=useMemo(()=>new Map(catalog.map(n=>[n.kind,n])),[catalog]);
 const pathFor=useCallback(edge=>{
  const a=positions[edge.from],b=positions[edge.to];if(!a||!b)return '';
  const ac=typeMap.get(byId.get(edge.from)?.kind),bc=typeMap.get(byId.get(edge.to)?.kind);
  const outIdx=Object.keys(ac?.outputs||{}).indexOf(edge.out),inIdx=Object.keys(bc?.inputs||{}).indexOf(edge.in);
  const x1=a.x+W,y1=a.y+39+Math.max(0,outIdx)*19,x2=b.x,y2=b.y+39+Math.max(0,inIdx)*19,dx=Math.max(45,Math.abs(x2-x1)/2);
  return `M ${x1} ${y1} C ${x1+dx} ${y1}, ${x2-dx} ${y2}, ${x2} ${y2}`;
 },[positions,byId,typeMap]);
 function startDrag(event,id){if(event.button!==0)return;event.stopPropagation();const p=positions[id];drag.current={id,startX:event.clientX,startY:event.clientY,orig:p};event.currentTarget.setPointerCapture(event.pointerId);onSelect(id);}
 function moveDrag(event){const d=drag.current;if(!d||!d.id)return;const dx=(event.clientX-d.startX)/viewport.zoom,dy=(event.clientY-d.startY)/viewport.zoom;onLayout({...layout,[d.id]:{x:snap(d.orig.x+dx),y:snap(d.orig.y+dy)}});}
 function endDrag(){drag.current=null;}
 function keyMove(event,id){if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();const delta={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]}[event.key],p=positions[id];onLayout({...layout,[id]:{x:p.x+delta[0],y:p.y+delta[1]}});}
 const minX=Math.min(0,...Object.values(positions).map(p=>p.x)),minY=Math.min(0,...Object.values(positions).map(p=>p.y));
 return <div className="p10-canvas-wrap">
  <div className="p10-canvas-bar"><strong>Canvas · {graph.nodes.length} Node</strong><button type="button" onClick={()=>onViewport({...viewport,zoom:between(viewport.zoom-.15,.25,2)})} aria-label="Zoom out">−</button><output aria-label="Zoom level">{Math.round(viewport.zoom*100)}%</output><button type="button" onClick={()=>onViewport({...viewport,zoom:between(viewport.zoom+.15,.25,2)})} aria-label="Zoom in">+</button><button type="button" onClick={()=>onViewport({x:0,y:0,zoom:1})}>Fit/Reset</button><button type="button" onClick={()=>onViewport({...viewport,x:viewport.x-60})}>←</button><button type="button" onClick={()=>onViewport({...viewport,x:viewport.x+60})}>→</button></div>
  <div className="p10-canvas" ref={surface} role="region" aria-label="Workflow graph. Nodes keyboard accessible" tabIndex={0}>
   <div className="p10-stage" style={{transform:`translate(${viewport.x}px,${viewport.y}px) scale(${viewport.zoom})`}}>
    <svg className="p10-wires" width="2000" height="1400" aria-hidden="true"><defs><marker id="p10-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0 0L7 3L0 6" fill="none" stroke="currentColor"/></marker></defs>{graph.edges.map((e,i)=><path key={i} d={pathFor(e)} className="p10-wire" markerEnd="url(#p10-arrow)"/>)}</svg>
    {graph.nodes.map(n=>{const types=typeMap.get(n.kind)||{inputs:{},outputs:{}},p=positions[n.id];return <article className={'p10-node '+(selected===n.id?'p10-node-active':'')} key={n.id} style={{left:p.x,top:p.y,width:W}} aria-label={`${n.kind} ${n.id}`}>
      <button className="p10-node-title" aria-pressed={selected===n.id} type="button" onClick={()=>onSelect(n.id)} onKeyDown={e=>keyMove(e,n.id)} onPointerDown={e=>startDrag(e,n.id)} onPointerMove={moveDrag} onPointerUp={endDrag} onLostPointerCapture={endDrag}><span>{n.kind.replaceAll('_',' ')}</span><small>{n.id}</small></button>
      <div className="p10-node-ports"><div>{Object.entries(types.inputs).map(([port,type])=><div key={port} title={type} className="p10-port p10-in"><i/>{port}<small>{type}</small></div>)}</div><div>{Object.entries(types.outputs).map(([port,type])=><div key={port} className="p10-port p10-out" title={type}>{port}<i/></div>)}</div></div>
    </article>})}</div>
  </div>
  <div className="p10-mini" aria-label="Graph minimap"><span>MINIMAP</span><div className="p10-mini-map">{graph.nodes.map(n=>{const p=positions[n.id];return <div key={n.id} title={n.id} className="p10-mini-node" style={{left:`${between((p.x-minX)/22,0,91)}%`,top:`${between((p.y-minY)/18,0,82)}%`}}/>})}</div></div>
  <p className="p10-muted">برای جابه‌جایی Nodeها، نوار عنوان را بکشید یا با کلیدهای جهت‌نما حرکت دهید. برای اتصال پورت‌ها از فرم قابل‌دسترس زیر Canvas استفاده کنید.</p>
 </div>;
}
