/* Phase03 owner-client adapter. Phase04 will integrate this with AuthProvider/UI.
 * No APP_INTERNAL_TOKEN, bearer/refresh token or per-user cache is persisted.
 */
export function createOwnerClient({fetchImpl = globalThis.fetch, onAuthLost = () => {}} = {}) {
  let csrf = null;
  let userId = null;
  let generation = 0;
  const objectUrls = new Set();

  function clearPrivateState() {
    csrf = null;
    userId = null;
    generation++;
    for (const url of objectUrls) {
      if (globalThis.URL?.revokeObjectURL) globalThis.URL.revokeObjectURL(url);
    }
    objectUrls.clear();
    // The existing pre-auth editor is not user-scoped. Keep it out of later accounts.
    // Browser privacy modes may block storage entirely. Logout must still work.
    try {
      if (globalThis.localStorage) {
        const keys = [];
        for (let i = 0; i < globalThis.localStorage.length; i++) {
          const key = globalThis.localStorage.key(i);
          if (key?.startsWith('comfyui-controller:')) keys.push(key);
        }
        for (const key of keys) globalThis.localStorage.removeItem(key);
      }
      globalThis.sessionStorage?.removeItem('comfyui-controller:pending-request');
    } catch { /* Auth state still invalidated in memory. */ }
  }

  async function session() {
    const started = generation;
    const response = await fetchImpl('/api/auth/session', { credentials: 'same-origin', cache: 'no-store' });
    if (!response.ok) throw new Error(`Session HTTP ${response.status}`);
    const data = await response.json();
    const nextId = data?.user?.id ?? null;
    if (started !== generation) return null;
    if (userId && userId !== nextId) clearPrivateState();
    userId = nextId;
    if (!nextId) clearPrivateState();
    return data;
  }

  async function request(path, {method='GET', headers={}, body, ...options}={}) {
    if (!/^\/api\/(jobs|job-requests|job-comparison|uploads|assets|user\/instance-status)(\/|\?|$)/.test(path)) {
      throw new Error('Owner client accepts only allowlisted API routes');
    }
    const requestGeneration=generation;
    const modifying=!['GET','HEAD'].includes(method.toUpperCase());
    if (modifying && !csrf) {
      const r=await fetchImpl('/api/auth/csrf',{credentials:'same-origin',cache:'no-store'});
      if (r.status===401){clearPrivateState();onAuthLost();throw new Error('Authentication required');}
      if (!r.ok)throw new Error(`CSRF HTTP ${r.status}`);
      const data=await r.json();csrf=data.csrf_token;
    }
    if (requestGeneration!==generation)throw new Error('Session changed during request');
    const h={...headers};
    if (modifying)h['X-CSRF-Token']=csrf;
    const r=await fetchImpl(path,{method,body,headers:h,credentials:'same-origin',cache:'no-store',...options});
    if (requestGeneration!==generation)throw new Error('Account changed during request');
    if (r.status===401){clearPrivateState();onAuthLost();}
    return r;
  }

  function registerObjectUrl(url) {objectUrls.add(url);return url;}
  return {session,request,clearPrivateState,registerObjectUrl};
}
