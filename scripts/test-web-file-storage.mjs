import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../swir-file-storage.js',import.meta.url),'utf8');
const explorer=fs.readFileSync(new URL('../swir-files.html',import.meta.url),'utf8');
const desktop=fs.readFileSync(new URL('../swir-v12.js',import.meta.url),'utf8');

function assert(ok,message){if(!ok)throw new Error(message)}

const window={};window.window=window;
vm.runInNewContext(source,{window,Date,JSON,Map,Set,Object,String,Number,Array,Promise,setTimeout,clearTimeout,console});
const api=window.SwirFileStorage;
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

assert(source.includes("DB_VERSION=2"),'storage adapter is not on IndexedDB v2');
assert(source.includes("PAYLOAD_STORE='payloads'"),'dedicated payload store missing');
assert(source.includes("transaction([STATE_STORE,PAYLOAD_STORE],'readwrite')"),'metadata and payload writes must be atomic');
assert(!source.includes('localStorage.'),'storage adapter must never use localStorage');

assert(explorer.includes('SwirFileStorage'),'File Explorer must use SwirFileStorage');
assert(!explorer.includes('localStorage.setItem(KEY'),'File Explorer must not persist the VFS to localStorage');
assert(explorer.includes('25*1024*1024'),'File Explorer must expose the larger IndexedDB import budget');
assert(explorer.includes('localStorage.getItem(KEY'),'legacy VFS import read is required');
assert(explorer.includes('localStorage.removeItem(KEY'),'legacy VFS mirror must be removed after migration');

assert(desktop.includes('SwirFileStorage'),'desktop context-menu VFS mutations must use SwirFileStorage');
assert(!desktop.includes('localStorage.setItem(VFS_KEY'),'desktop context menu must not recreate the legacy VFS mirror');

console.log(JSON.stringify({schema:'swir.web-file-storage-contract/2.0',valid:true,metadata:metadata.length,payloads:payloads.length}));
