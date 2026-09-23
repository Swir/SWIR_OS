import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../swir-file-storage.js',import.meta.url),'utf8');
const explorer=fs.readFileSync(new URL('../swir-files.html',import.meta.url),'utf8');
const desktop=fs.readFileSync(new URL('../swir-v12.js',import.meta.url),'utf8');

function assert(ok,message){if(!ok)throw new Error(message)}
function defer(fn){setTimeout(fn,0)}

function createFakeIndexedDB(){
  class FakeTransaction{
    constructor(db,names,mode){this.db=db;this.names=Array.isArray(names)?names:[names];this.mode=mode;this.pending=0;this.closed=false;this.error=null;this.oncomplete=null;this.onerror=null;this.onabort=null}
    objectStore(name){
      if(this.closed)throw new Error('TransactionInactiveError');
      if(!this.names.includes(name))throw new Error(`Store ${name} is outside transaction scope`);
      const store=this.db.stores.get(name);if(!store)throw new Error(`Missing object store ${name}`);
      const request=(operation)=>{
        if(this.closed)throw new Error('TransactionInactiveError');
        this.pending++;
        const req={result:undefined,error:null,onsuccess:null,onerror:null};
        defer(()=>{
          try{req.result=operation();req.onsuccess?.({target:req})}
          catch(err){req.error=err;this.error=err;req.onerror?.({target:req});this.onerror?.({target:this})}
          finally{this.pending--;this.maybeComplete()}
        });
        return req;
      };
      return {
        get:key=>request(()=>store.records.get(key)),
        getAll:()=>request(()=>[...store.records.values()].map(value=>structuredClone(value))),
        put:(value,key)=>request(()=>{const resolved=store.keyPath?value?.[store.keyPath]:key;if(resolved===undefined)throw new Error('DataError');store.records.set(resolved,structuredClone(value));return resolved}),
        clear:()=>request(()=>{store.records.clear();return undefined})
      };
    }
    maybeComplete(){if(this.pending!==0||this.closed)return;defer(()=>{if(this.pending===0&&!this.closed){this.closed=true;this.oncomplete?.({target:this})}})}
  }
  class FakeDatabase{
    constructor(name,version=0){this.name=name;this.version=version;this.stores=new Map();this.objectStoreNames={contains:name=>this.stores.has(name)}}
    createObjectStore(name,options={}){if(this.stores.has(name))throw new Error('ConstraintError');const store={keyPath:options.keyPath||null,records:new Map()};this.stores.set(name,store);return store}
    transaction(names,mode='readonly'){return new FakeTransaction(this,names,mode)}
  }
  const databases=new Map();
  return {
    open(name,version){
      const req={result:undefined,error:null,onsuccess:null,onerror:null,onupgradeneeded:null};
      defer(()=>{
        try{
          let db=databases.get(name);if(!db){db=new FakeDatabase(name,0);databases.set(name,db)}
          const oldVersion=db.version;if(version<oldVersion)throw new Error('VersionError');
          req.result=db;
          if(version>oldVersion){db.version=version;req.onupgradeneeded?.({oldVersion,newVersion:version,target:req})}
          req.onsuccess?.({target:req});
        }catch(err){req.error=err;req.onerror?.({target:req})}
      });
      return req;
    },
    seed(name,{version=1,state=null,payloads=[]}={}){
      const db=new FakeDatabase(name,version);db.createObjectStore('state');
      if(state)db.stores.get('state').records.set('explorer',structuredClone(state));
      if(payloads!==null){db.createObjectStore('payloads',{keyPath:'id'});for(const payload of payloads)db.stores.get('payloads').records.set(payload.id,structuredClone(payload))}
      databases.set(name,db);
    },
    snapshot(name){
      const db=databases.get(name);if(!db)return null;
      return {version:db.version,stores:Object.fromEntries([...db.stores].map(([key,store])=>[key,[...store.records.entries()].map(([id,value])=>[id,structuredClone(value)])]))};
    }
  };
}

function loadAdapter(indexedDB){
  const window={indexedDB};window.window=window;
  vm.runInNewContext(source,{window,indexedDB,Date,JSON,Map,Set,Object,String,Number,Array,Promise,setTimeout,clearTimeout,console,structuredClone});
  return window.SwirFileStorage;
}

const indexedDB=createFakeIndexedDB();
let api=loadAdapter(indexedDB);
assert(api,'SwirFileStorage was not registered');
assert(api.info().databaseVersion===2,'IndexedDB schema version must be 2');

const sample=[
  {id:'folder',type:'folder',name:'Folder',parent:'root'},
  {id:'text',type:'file',name:'a.txt',encoding:'text',content:'hello',size:5,parent:'root'},
  {id:'bin',type:'file',name:'a.bin',encoding:'dataurl',dataUrl:'data:application/octet-stream;base64,AAEC',size:3,parent:'root'}
];
const {metadata,payloads}=api._test.splitItems(sample);
assert(metadata.length===3&&payloads.length===2,'payload split count mismatch');
assert(metadata.every(item=>!('content'in item)&&!('dataUrl'in item)),'metadata must not contain inline payloads');
assert(payloads.some(p=>p.id==='text'&&p.content==='hello'),'text payload missing');
assert(payloads.some(p=>p.id==='bin'&&p.dataUrl.startsWith('data:')),'binary payload missing');
const hydrated=api._test.hydrateItems(metadata,payloads);
assert(hydrated.find(i=>i.id==='text')?.content==='hello','text payload hydration failed');
assert(hydrated.find(i=>i.id==='bin')?.dataUrl?.startsWith('data:'),'binary payload hydration failed');

const first=await api.load({legacyItems:sample});
assert(first.items.find(i=>i.id==='text')?.content==='hello','legacy handoff lost text payload');
assert(api.info().provider==='web-indexeddb','Web storage must use IndexedDB when available');
let snap=indexedDB.snapshot('swir-file-explorer');
const storedState=Object.fromEntries(snap.stores.state).explorer;
assert(storedState.items.every(item=>!('content'in item)&&!('dataUrl'in item)),'IndexedDB state record still contains payloads');
assert(snap.stores.payloads.length===2,'IndexedDB payload store count mismatch');

const largeData='data:application/octet-stream;base64,'+'A'.repeat(3*1024*1024);
await api.save([{id:'large',type:'file',name:'large.bin',encoding:'dataurl',dataUrl:largeData,size:3*1024*1024,parent:'root'}]);
api=loadAdapter(indexedDB);
const largeReload=await api.load();
assert(largeReload.items[0]?.dataUrl===largeData,'multi-megabyte payload did not survive IndexedDB reload');
assert(api.info().persistent===true,'IndexedDB provider must report persistent storage');

const migrationDB=createFakeIndexedDB();
migrationDB.seed('swir-file-explorer',{version:1,state:{schema:'swir.file-explorer-state/1.0',version:1,revision:7,updatedAt:'2026-09-23T00:00:00.000Z',items:sample},payloads:null});
api=loadAdapter(migrationDB);
const migrated=await api.load();
assert(migrated.revision===7,'v1 migration must preserve revision');
assert(migrated.items.find(i=>i.id==='bin')?.dataUrl?.startsWith('data:'),'v1 inline payload was not preserved during migration');
snap=migrationDB.snapshot('swir-file-explorer');
assert(snap.version===2,'v1 database was not upgraded to v2');
assert(Object.fromEntries(snap.stores.state).explorer.items.every(item=>!('content'in item)&&!('dataUrl'in item)),'v1 inline payloads were not split after migration');
assert(snap.stores.payloads.length===2,'v1 migration did not populate payload store');

assert(source.includes("DB_VERSION=2"),'storage adapter is not on IndexedDB v2');
assert(source.includes("PAYLOAD_STORE='payloads'"),'dedicated payload store missing');
assert(source.includes("transaction([STATE_STORE,PAYLOAD_STORE],'readwrite')"),'metadata and payload writes must be atomic');
assert(source.includes('Promise.all(['),'IndexedDB read requests must be issued before awaiting transaction results');
assert(!source.includes('localStorage.'),'storage adapter must never use localStorage');

assert(explorer.includes('SwirFileStorage'),'File Explorer must use SwirFileStorage');
assert(!explorer.includes('localStorage.setItem(KEY'),'File Explorer must not persist the VFS to localStorage');
assert(explorer.includes('25*1024*1024'),'File Explorer must expose the larger IndexedDB import budget');
assert(explorer.includes('localStorage.getItem(KEY'),'legacy VFS import read is required');
assert(explorer.includes('localStorage.removeItem(KEY'),'legacy VFS mirror must be removed after migration');

assert(desktop.includes('SwirFileStorage'),'desktop context-menu VFS mutations must use SwirFileStorage');
assert(!desktop.includes('localStorage.setItem(VFS_KEY'),'desktop context menu must not recreate the legacy VFS mirror');

console.log(JSON.stringify({schema:'swir.web-file-storage-contract/2.1',valid:true,metadata:metadata.length,payloads:payloads.length,largePayloadBytes:3*1024*1024,migratedRevision:migrated.revision}));
