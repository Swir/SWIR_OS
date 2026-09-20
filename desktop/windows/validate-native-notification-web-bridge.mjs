import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=fs.readFileSync('swir-notifications.js','utf8');
for(const needle of [
  "const notifications=window.SWIR_NATIVE_HOST?.notifications",
  "const show=notifications?.show",
  "if(typeof show!=='function')return null",
  "const showWithActions = notifications?.showWithActions",
  "if (actions.length && typeof showWithActions === 'function')",
  "const nativeDelivery=await deliverNative(item)",
  "if(!nativeDelivery)window.SwirOS?.toast?.(item.title,item.message)",
  "const nativeInvoke = window.SWIR_NATIVE_HOST?.notifications?.invokeAction"
]){
  assert.ok(source.includes(needle),`Missing native notification bridge invariant: ${needle}`);
}

const storage=new Map([['swir-installed-apps',JSON.stringify(['chat'])]]);
const events=[];const nativeCalls=[];const nativeActionDeliveries=[];const nativeActionInvocations=[];const toasts=[];
class CustomEvent{constructor(type,init={}){this.type=type;this.detail=init.detail}}
const window={
  SWIR_PACKAGE_CATALOG:[{id:'chat',packageId:'swir.chat',name:'Chat',permissions:['notifications']}],
  SwirPlatform:{permissions:{get:async()=>({value:true})}},
  SWIR_NATIVE_HOST:{notifications:{
    show:async(...args)=>{nativeCalls.push(args);return {delivered:true,provider:'test-native'}},
    showWithActions:async(...args)=>{nativeActionDeliveries.push(args);return {delivered:true,provider:'test-native-actions'}},
    invokeAction:async detail=>{nativeActionInvocations.push(detail);return {handled:true}}
  }},
  SwirOS:{toast:(...args)=>toasts.push(args)},
  dispatchEvent:event=>events.push(event)
};
const context={window,localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},CustomEvent,Date,Math,JSON,String,Array,Object,Error,TypeError,Set};
vm.createContext(context);vm.runInContext(source,context);

const result=await window.SwirNotifications.send('chat',{title:'Hello',message:'Desktop',silent:true});
assert.equal(nativeCalls.length,1,'legacy native notification provider must be called exactly once when no actions are present');
assert.deepEqual(nativeCalls[0],['Hello','Desktop','swir.chat',true]);
assert.equal(nativeActionDeliveries.length,0,'action-aware provider must not be used when no actions are present');
assert.equal(result.nativeDelivery.delivered,true);
assert.equal(toasts.length,0,'shell toast must not duplicate a delivered native notification');
assert.equal(events.at(-1)?.detail?.nativeDelivery?.provider,'test-native');

const actionable=await window.SwirNotifications.send('chat',{
  title:'Action',
  message:'Open chat',
  actions:[{id:'open-chat',label:'Open',type:'open-app',targetApp:'chat'}]
});
assert.equal(nativeActionDeliveries.length,1,'action-aware native notification provider must receive actionable notifications');
assert.deepEqual(nativeActionDeliveries[0].slice(0,4),['Action','Open chat','swir.chat',false]);
assert.equal(
  JSON.stringify(nativeActionDeliveries[0][4]),
  JSON.stringify([{id:'open-chat',label:'Open',type:'open-app',targetApp:'chat'}]),
  'native action payload must remain declarative across the VM bridge'
);
assert.equal(actionable.nativeDelivery.provider,'test-native-actions');
assert.equal(toasts.length,0,'actionable native delivery must not be duplicated as a shell toast');

const actionResult=await window.SwirNotifications.invokeAction(actionable.id,'open-chat');
assert.equal(nativeActionInvocations.length,1,'native action bridge must be invoked exactly once');
assert.equal(nativeActionInvocations[0].notificationId,actionable.id);
assert.equal(nativeActionInvocations[0].actionId,'open-chat');
assert.equal(nativeActionInvocations[0].actionType,'open-app');
assert.equal(nativeActionInvocations[0].targetApp,'chat');
assert.equal(actionResult.nativeResult.handled,true);
assert.equal(events.at(-1)?.type,'swir:notification-action');
assert.equal(events.at(-1)?.detail?.actionId,'open-chat');

window.SWIR_NATIVE_HOST={};
const fallback=await window.SwirNotifications.send('chat',{title:'Fallback',message:'Web'});
assert.equal(fallback.nativeDelivery,null);
assert.equal(toasts.length,1,'web fallback toast must remain available when no native provider exists');

console.log('SWIR native notification web bridge contract: PASS');
