/* SWIR OS File Explorer Storage Adapter 2.0 — split IndexedDB metadata/payloads + native Desktop */
(() => {
  'use strict';
  const SCHEMA='swir.file-explorer-state/1.0';
  const NATIVE_MANIFEST='.swir-file-explorer-v1.json';
  const DB_NAME='swir-file-explorer';
  const DB_VERSION=2;
  const STATE_STORE='state';
  const PAYLOAD_STORE='payloads';
  const RECORD_KEY='explorer';
  let dbPromise=null;
  let provider='initializing';
  let revision=0;
  let memoryState=null;

  function normalize(items){
    if(!Array.isArray(items))return[];
    return items.filter(item=>item&&typeof item==='object').map(item=>item.type==='text'?{...item,type:'file',mime:'text/plain',encoding:'text',size:String(item.content||'').length}:{...item});
  }

  function splitItems(items){
    const metadata=[];const payloads=[];
    for(const raw of normalize(items)){
      const item={...raw};
      const payload={id:String(item.id||'')};
      let hasPayload=false;
      if(Object.prototype.hasOwnProperty.call(item,'content')){payload.content=item.content;delete item.content;hasPayload=true}
      if(Object.prototype.hasOwnProperty.call(item,'dataUrl')){payload.dataUrl=item.dataUrl;delete item.dataUrl;hasPayload=true}
      metadata.push(item);
      if(hasPayload&&payload.id)payloads.push(payload);
    }
    return {metadata,payloads};
  }

  function hydrateItems(metadata,payloads=[]){
    const byId=new Map(payloads.filter(Boolean).map(p=>[String(p.id||''),p]));
    return normalize(metadata).map(item=>{const p=byId.get(String(item.id||''));return p?{...item,...('content'in p?{content:p.content}:{}),...('dataUrl'in p?{dataUrl:p.dataUrl}:{})}:item});
  }

  function parseState(value){
    if(!value)return null;
    const parsed=typeof value==='string'?JSON.parse(value):value;
    if(parsed.schema!==SCHEMA||!Array.isArray(parsed.items))throw new Error('Unsupported File Explorer storage schema');
    revision=Math.max(revision,Number.isSafeInteger(parsed.revision)?parsed.revision:0);
    return {schema:SCHEMA,version:1,revision:Number.isSafeInteger(parsed.revision)?parsed.revision:0,updatedAt:parsed.updatedAt||null,items:normalize(parsed.items)};
  }

  function makeState(items,nextRevision){return {schema:SCHEMA,version:1,revision:nextRevision,updatedAt:new Date().toISOString(),items:normalize(items)}}

  async function waitForRuntime(timeoutMs=5000){
    if(window.SwirRuntime?.filesystem)return window.SwirRuntime.filesystem;
    if(!window.chrome?.webview)return null;
    const started=Date.now();
    while(!window.SwirRuntime?.filesystem&&Date.now()-started<timeoutMs)await new Promise(resolve=>setTimeout(resolve,25));
    return window.SwirRuntime?.filesystem||null;
  }

  async function nativeFilesystem(){
    const fs=await waitForRuntime();if(!fs?.info)return null;
    try{const info=await fs.info();return info?.native===true||info?.provider==='native-sandbox'?fs:null}catch{return null}
  }

  function openDb(){
    if(dbPromise)return dbPromise;
    dbPromise=new Promise((resolve,reject)=>{
      if(!('indexedDB'in window))return reject(new Error('IndexedDB unavailable'));
      const request=indexedDB.open(DB_NAME,DB_VERSION);
      request.onupgradeneeded=()=>{const db=request.result;if(!db.objectStoreNames.contains(STATE_STORE))db.createObjectStore(STATE_STORE);if(!db.objectStoreNames.contains(PAYLOAD_STORE))db.createObjectStore(PAYLOAD_STORE,{keyPath:'id'})};
      request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error||new Error('IndexedDB open failed'));
    });return dbPromise;
  }

  function requestResult(req,label){return new Promise((resolve,reject)=>{req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error||new Error(label))})}

  async function idbRead(){
    const db=await openDb();const tx=db.transaction([STATE_STORE,PAYLOAD_STORE],'readonly');
    const states=tx.objectStore(STATE_STORE),payloadStore=tx.objectStore(PAYLOAD_STORE);
    const stateRequest=states.get(RECORD_KEY),payloadRequest=payloadStore.getAll();
    const [state,payloads]=await Promise.all([
      requestResult(stateRequest,'IndexedDB state read failed'),
      requestResult(payloadRequest,'IndexedDB payload read failed')
    ]);
    if(!state)return null;
    const parsed=parseState(state);const hasInline=parsed.items.some(i=>Object.prototype.hasOwnProperty.call(i,'content')||Object.prototype.hasOwnProperty.call(i,'dataUrl'));
    const hydrated={...parsed,items:hasInline?parsed.items:hydrateItems(parsed.items,payloads||[])};
    if(hasInline)await idbPut(hydrated);
    return hydrated;
  }

  async function idbPut(state){
    const db=await openDb();const split=splitItems(state.items);
    const stored={...state,items:split.metadata};
    await new Promise((resolve,reject)=>{const tx=db.transaction([STATE_STORE,PAYLOAD_STORE],'readwrite');const states=tx.objectStore(STATE_STORE),payloads=tx.objectStore(PAYLOAD_STORE);states.put(stored,RECORD_KEY);payloads.clear();for(const p of split.payloads)payloads.put(p);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error||new Error('IndexedDB write failed'));tx.onabort=()=>reject(tx.error||new Error('IndexedDB write aborted'))});
  }

  async function load({legacyItems=[]}={}){
    const fs=await nativeFilesystem();
    if(fs){provider='desktop-native-manifest';const record=await fs.get(NATIVE_MANIFEST);if(record?.content)return parseState(record.content);const state=makeState(legacyItems,revision+1);await fs.save({id:NATIVE_MANIFEST,name:NATIVE_MANIFEST,content:JSON.stringify(state)});revision=state.revision;return state}
    provider='web-indexeddb';let existing=null;
    try{existing=await idbRead()}catch(err){if(String(err?.message||err).includes('schema'))throw err;provider='web-memory-fallback';existing=parseState(memoryState)}
    if(existing)return existing;
    const state=makeState(legacyItems,revision+1);if(provider==='web-indexeddb')await idbPut(state);else memoryState=state;revision=state.revision;return state;
  }

  async function save(items){
    const fs=await nativeFilesystem();
    if(fs){provider='desktop-native-manifest';let current=null;try{const record=await fs.get(NATIVE_MANIFEST);if(record?.content)current=parseState(record.content)}catch{}const state=makeState(items,Math.max(revision,current?.revision||0)+1);await fs.save({id:NATIVE_MANIFEST,name:NATIVE_MANIFEST,content:JSON.stringify(state)});revision=state.revision;return state}
    provider='web-indexeddb';let current=null;
    try{current=await idbRead()}catch(err){if(String(err?.message||err).includes('schema'))throw err;provider='web-memory-fallback';current=parseState(memoryState)}
    const state=makeState(items,Math.max(revision,current?.revision||0)+1);if(provider==='web-indexeddb')await idbPut(state);else memoryState=state;revision=state.revision;return state;
  }

  window.SwirFileStorage={schema:SCHEMA,nativeManifest:NATIVE_MANIFEST,load,save,normalize,info:()=>({provider,schema:SCHEMA,nativeManifest:provider==='desktop-native-manifest'?NATIVE_MANIFEST:null,revision,database:provider==='web-indexeddb'?DB_NAME:null,databaseVersion:DB_VERSION,payloadStore:provider==='web-indexeddb'?PAYLOAD_STORE:null,persistent:provider!=='web-memory-fallback'}),_test:{splitItems,hydrateItems}};
})();
