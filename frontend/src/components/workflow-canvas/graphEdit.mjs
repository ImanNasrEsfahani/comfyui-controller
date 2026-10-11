/** Pure, unit-testable semantic Studio transformations. Never constructs ComfyUI class_type. */
export const emptyLayout=()=>({});
export const initialViewport=()=>({x:0,y:0,zoom:1});
export const between=(x,min,max)=>Math.max(min,Math.min(max,x));
export const snap=(value,grid=20)=>Math.round(value/grid)*grid;
export function addNode(graph,kind,catalog){
 if(!catalog.some(item=>item.kind===kind))throw Error('Node not allowed');
 const used=new Set(graph.nodes.map(x=>x.id));let i=1;while(used.has(`node${i}`))i++;
 const node={id:`node${i}`,kind};return {...graph,nodes:[...graph.nodes,node]};
}
export function removeNode(graph,id){
 return {...graph,nodes:graph.nodes.filter(n=>n.id!==id),edges:graph.edges.filter(e=>e.from!==id&&e.to!==id),inputs:graph.inputs.filter(i=>i.node!==id),outputs:graph.outputs.filter(o=>o.node!==id)};
}
export function checkEdge(graph,edge,catalog){
 const ids=new Map(graph.nodes.map(n=>[n.id,n.kind]));const types=new Map(catalog.map(x=>[x.kind,x]));
 const src=types.get(ids.get(edge.from)),dest=types.get(ids.get(edge.to));
 if(!src||!dest||!Object.hasOwn(src.outputs,edge.out)||!Object.hasOwn(dest.inputs,edge.in))return 'Unknown port';
 const a=src.outputs[edge.out],b=dest.inputs[edge.in];
 if(a!==b&&!(a==='integer'&&b==='number'))return 'Incompatible ports';
 if(graph.edges.some(e=>e.to===edge.to&&e.in===edge.in)||graph.inputs.some(i=>i.node===edge.to&&i.port===edge.in))return 'Port already used';
 if(edge.from===edge.to)return 'Cycles not allowed';
 const adjacency=new Map(graph.nodes.map(n=>[n.id,[]]));for(const e of graph.edges)adjacency.get(e.from)?.push(e.to);
 const stack=[edge.to],seen=new Set();while(stack.length){let node=stack.pop();if(node===edge.from)return 'Cycles not allowed';if(seen.has(node))continue;seen.add(node);stack.push(...(adjacency.get(node)||[]));}
 return null;
}
export function addEdge(graph,edge,catalog){const error=checkEdge(graph,edge,catalog);if(error)throw Error(error);return {...graph,edges:[...graph.edges,edge]};}
export function bindInput(graph,input,catalog){
 const current=graph.nodes.find(n=>n.id===input.node),kind=catalog.find(x=>x.kind===current?.kind);
 if(!kind||kind.inputs?.[input.port]!==input.type||graph.edges.some(e=>e.to===input.node&&e.in===input.port)||graph.inputs.some(i=>i.node===input.node&&i.port===input.port)||graph.inputs.some(i=>i.key===input.key)||!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(input.key)||!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(input.role))throw Error('Invalid input port/key/role');
 return {...graph,inputs:[...graph.inputs,input]};
}
export function unbindInput(graph,key){return {...graph,inputs:graph.inputs.filter(i=>i.key!==key)};}
export function outputBinding(graph,id){const n=graph.nodes.find(n=>n.id===id);if(!n||!['image_output','video_output'].includes(n.kind))throw Error('Not an output node');return {...graph,outputs:[...graph.outputs.filter(o=>o.node!==id),{node:id,media_type:n.kind==='image_output'?'image':'video'}]};}
export function createHistory(graph,layout={}){return {past:[],present:{graph,layout},future:[]};}
export function commit(history,graph,layout=history.present.layout){
 const present={graph,layout};if(JSON.stringify(present)===JSON.stringify(history.present))return history;
 return {past:[...history.past.slice(-39),history.present],present,future:[]};
}
export function undo(history){if(!history.past.length)return history;return {past:history.past.slice(0,-1),present:history.past.at(-1),future:[history.present,...history.future]};}
export function redo(history){if(!history.future.length)return history;return {past:[...history.past,history.present],present:history.future[0],future:history.future.slice(1)};}
export function diffGraph(a,b){
 const key=x=>`${x.id}:${x.kind}`,setA=new Set(a.nodes.map(key)),setB=new Set(b.nodes.map(key));
 const edgeKey=e=>`${e.from}.${e.out}→${e.to}.${e.in}`,ea=new Set(a.edges.map(edgeKey)),eb=new Set(b.edges.map(edgeKey));
 return {nodes_added:[...setB].filter(x=>!setA.has(x)),nodes_removed:[...setA].filter(x=>!setB.has(x)),edges_added:[...eb].filter(x=>!ea.has(x)),edges_removed:[...ea].filter(x=>!eb.has(x))};
}
export function safeLayout(layout,graph){return Object.fromEntries(Object.entries(layout).filter(([key,v])=>graph.nodes.some(n=>n.id===key)&&Number.isFinite(v?.x)&&Number.isFinite(v?.y)).map(([key,v])=>[key,{x:snap(v.x),y:snap(v.y)}]));}
