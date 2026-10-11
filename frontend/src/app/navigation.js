/** Lightweight route solution: history API + popstate, no network dependencies. */
export function navigate(to,{replace=false}={}) {
  if(typeof to!=='string' || !to.startsWith('/') || to.startsWith('//') || to.includes('\\')) throw new Error('Unsafe navigation');
  if(replace) window.history.replaceState({},'',to);
  else window.history.pushState({},'',to);
  window.dispatchEvent(new Event('comfyui:navigate'));
}
export function currentLocation(){return window.location.pathname+window.location.search;}
export function subscribeLocation(callback){
  window.addEventListener('popstate',callback);
  window.addEventListener('comfyui:navigate',callback);
  return ()=>{window.removeEventListener('popstate',callback);window.removeEventListener('comfyui:navigate',callback);};
}
