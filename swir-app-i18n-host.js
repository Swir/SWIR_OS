(()=>{
  'use strict';
  const HELPER='./swir-app-i18n.js';
  function isSwirRootApp(frame){
    try{
      const url=new URL(frame.getAttribute('src')||frame.src,location.href);
      const name=(url.pathname.split('/').pop()||'').toLowerCase();
      return url.origin===location.origin&&/^swir-[a-z0-9-]+\.html$/.test(name);
    }catch{return false}
  }
  function inject(frame){
    if(!(frame instanceof HTMLIFrameElement)||!isSwirRootApp(frame)) return false;
    try{
      const doc=frame.contentDocument;
      if(!doc?.documentElement||doc.querySelector('script[data-swir-app-i18n]')) return false;
      const script=doc.createElement('script');
      script.dataset.swirAppI18n='1';
      script.src=new URL(HELPER,location.href).href;
      (doc.head||doc.documentElement).appendChild(script);
      return true;
    }catch{return false}
  }
  function watch(frame){
    if(!(frame instanceof HTMLIFrameElement)||frame.dataset.swirI18nWatched==='1') return;
    frame.dataset.swirI18nWatched='1';
    frame.addEventListener('load',()=>inject(frame));
    if(frame.contentDocument?.readyState==='complete'||frame.contentDocument?.readyState==='interactive') inject(frame);
  }
  function scan(root=document){
    if(root instanceof HTMLIFrameElement) watch(root);
    root.querySelectorAll?.('iframe').forEach(watch);
  }
  function start(){
    scan(document);
    const layer=document.querySelector('#window-layer')||document.body;
    new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{if(node.nodeType===1)scan(node)}))).observe(layer,{childList:true,subtree:true});
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true}); else start();
  window.SwirAppI18nHost=Object.freeze({contract:'swir.app-i18n-host/0.1',helper:HELPER,isSwirRootApp});
})();
