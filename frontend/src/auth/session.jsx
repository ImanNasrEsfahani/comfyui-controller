import React, {createContext, useCallback, useContext, useEffect, useMemo, useRef, useState} from 'react';
import {authRequest} from './api.js';
import {createOwnerClient} from '../ownerClient.js';

const AuthContext=createContext(null);
const EMPTY=Object.freeze({state:'unknown',user:null});
const CHANNEL='comfyui-controller-auth';

export function AuthProvider({children}) {
  const [session,setSession]=useState(EMPTY);
  const [epoch,setEpoch]=useState(0);
  const currentUserId=useRef(null);
  const generation=useRef(0);
  const active=useRef(new Set());
  const channel=useRef(null);
  const client=useMemo(()=>createOwnerClient({onAuthLost:()=>{invalidate(false);}}),[]);

  const wipe=useCallback(()=>{
    generation.current++;
    for(const controller of active.current) controller.abort();
    active.current.clear();
    client.clearPrivateState();
    setEpoch(v=>v+1);
  },[client]);

  const invalidate=useCallback((broadcast=true)=>{
    wipe();currentUserId.current=null;
    setSession({state:'anonymous',user:null});
    if(broadcast) channel.current?.postMessage({type:'changed'});
  },[wipe]);

  const refresh=useCallback(async()=>{
    const run=++generation.current;
    const controller=new AbortController();active.current.add(controller);
    try {
      const data=await authRequest('/session',{signal:controller.signal});
      if (generation.current!==run) return null;
      const nextId=data?.user?.id || null;
      if(currentUserId.current !== nextId) wipe();
      currentUserId.current=nextId;
      setSession(nextId?{state:'authenticated',user:data.user}:{state:'anonymous',user:null});
      return data;
    } catch(error) {
      if (generation.current!==run || controller.signal.aborted) return null;
      wipe();currentUserId.current=null;
      // Network/503 must not grant access or imply a confirmed anonymous state.
      setSession({state:'unavailable',user:null});
      return null;
    } finally {active.current.delete(controller);}
  },[wipe]);

  useEffect(()=>{
    const channelInstance=typeof BroadcastChannel!=='undefined' ? new BroadcastChannel(CHANNEL):null;
    channel.current=channelInstance;
    if(channelInstance) channelInstance.onmessage=(event)=>{
      if(event.data?.type==='changed') {wipe();currentUserId.current=null;setSession(EMPTY);void refresh();}
    };
    const focus=()=>{wipe();currentUserId.current=null;setSession(EMPTY);void refresh();};
    const visibility=()=>{if(document.visibilityState==='visible')focus();};
    window.addEventListener('focus',focus);
    document.addEventListener('visibilitychange',visibility);
    void refresh();
    return ()=>{channelInstance?.close();window.removeEventListener('focus',focus);document.removeEventListener('visibilitychange',visibility);wipe();};
  },[refresh,wipe]);

  const login=useCallback(async(body)=>{
    await authRequest('/login',{method:'POST',body});
    // No optimistic authentication: server must validate the newly set Cookie.
    currentUserId.current=null;wipe();setSession(EMPTY);
    const validated=await refresh();
    if(!validated?.user?.id) throw new Error('نشست تأیید نشد؛ مجدداً تلاش کنید.');
    channel.current?.postMessage({type:'changed'});
    return validated;
  },[refresh,wipe]);
  const logout=useCallback(async()=>{
    let error=null;
    try {
      const token=(await authRequest('/csrf')).csrf_token;
      await authRequest('/logout',{method:'POST',csrfToken:token});
    } catch(err) {error=err;}
    invalidate();
    if(error) throw error;
  },[invalidate]);
  const mutationToken=useCallback(async()=>(await authRequest('/csrf')).csrf_token,[]);
  const value=useMemo(()=>({session,epoch,login,logout,refresh,invalidate,mutationToken,ownerClient:client}),[session,epoch,login,logout,refresh,invalidate,mutationToken,client]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(){const ctx=useContext(AuthContext);if(!ctx)throw new Error('AuthProvider missing');return ctx;}
