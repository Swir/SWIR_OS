(()=>{
  'use strict';
  function parentI18n(){try{return parent.SwirI18n||null}catch{return null}}
  const page=(location.pathname.split('/').pop()||'').toLowerCase();
  const bindings={
    'swir-files.html':[
      ['#home','files.home'],['[data-view="home"]','files.home','⌂ '],['[data-view="apps"]','files.apps','◫ '],['[data-view="documents"]','files.documents','▤ '],['[data-view="appdata"]','files.appData','◇ '],['[data-view="trash"]','files.trash','⌫ '],
      ['#importFile','files.import'],['#newFolder','files.newFolder','+ '],['#newText','files.newText','+ '],['#emptyTrash','files.emptyTrash']
    ],
    'swir-store.html':[
      ['#search','store.search','', 'placeholder'],['#audit','store.audit'],['#importBtn','store.installPackage'],['#spec','store.packageSpec'],['#defaults','store.defaultApps'],['#applyNow','store.apply']
    ],
    'swir-updates.html':[
      ['h1','updates.title'],['.grid .card:nth-child(1) strong','updates.repository'],['.grid .card:nth-child(2) strong','updates.serviceWorker'],['.grid .card:nth-child(3) strong','updates.network'],['.grid .card:nth-child(4) strong','updates.cache'],['.grid .card:nth-child(5) strong','updates.desktopHost'],['.grid .card:nth-child(6) strong','updates.desktopFeed'],['.grid .card:nth-child(7) strong','updates.desktopPreparation'],['.grid .card:nth-child(8) strong','updates.desktopRestart'],
      ['#store','updates.openStore'],['#reload','updates.reloadSystem'],['#clear','updates.clearCache'],['#repoOpen','updates.openGithub']
    ],
    'swir-settings.html':[
      ['h1','system.settings'],['#saveAll','settings.save'],['[data-tab="general"]','settings.general'],['[data-tab="language"]','settings.languageRegion'],['[data-tab="appearance"]','settings.appearance'],['[data-tab="audio"]','settings.audio'],['[data-tab="session"]','settings.session'],['[data-tab="storage"]','settings.storage'],['[data-tab="system"]','settings.system'],
      ['[data-section="general"] h2','settings.general'],['[data-section="language"] h2','settings.languageRegion'],['[data-section="appearance"] h2','settings.appearance'],['[data-section="audio"] h2','settings.audio'],['[data-section="session"] h2','settings.session'],['[data-section="storage"] h2','settings.storage'],['[data-section="system"] h2','settings.system'],
      ['[data-section="general"] .field label','settings.deviceName'],['[data-section="language"] .field label','settings.systemLocale'],['#useBrowserLocale','settings.useDeviceLocale'],['#previewLocale','settings.preview']
    ]
  };

  function apply(){
    const i18n=parentI18n();
    if(!i18n?.t) return 0;
    document.documentElement.lang=i18n.locale||'en';
    document.documentElement.dir=i18n.direction||'ltr';
    document.documentElement.dataset.locale=i18n.locale||'en';
    let count=0;
    for(const [selector,key,prefix='',mode='text'] of bindings[page]||[]){
      for(const node of document.querySelectorAll(selector)){
        const text=i18n.t(key,{},{fallback:''});
        if(!text) continue;
        if(mode==='placeholder'&&'placeholder' in node) node.placeholder=`${prefix}${text}`;
        else node.textContent=`${prefix}${text}`;
        count++;
      }
    }
    return count;
  }

  let unsubscribe=null;
  function start(){
    apply();
    const i18n=parentI18n();
    if(i18n?.subscribe) unsubscribe=i18n.subscribe(()=>apply());
  }
  addEventListener('pagehide',()=>{try{unsubscribe?.()}catch{}},{once:true});
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true}); else start();
  window.SwirAppI18n=Object.freeze({contract:'swir.app-i18n/0.1',page,apply,bindings:Object.freeze(Object.keys(bindings))});
})();
