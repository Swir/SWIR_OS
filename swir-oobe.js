/* SWIR OS 1.7 — Localized First Boot Setup */
(() => {
  'use strict';
  const $=(s,r=document)=>r.querySelector(s);
  const LOCALE_PRESETS=Object.freeze(['en-US','pl-PL','nb-NO','de-DE','es-ES','fr-FR','it-IT','pt-BR','uk-UA','ru-RU','tr-TR','ar-SA','he-IL','ja-JP','zh-Hans-CN']);

  function i18n(){return window.SwirI18n||null}
  function tr(key,vars,fallback=key){return i18n()?.t?.(key,vars,{fallback})??fallback}

  async function waitForPlatform(){
    let attempts=0;
    while(!window.SwirPlatform?.identity||!window.SwirPlatform?.settings){
      attempts++;
      if(attempts===40&&window.SwirPlatform&&!sessionStorage.getItem('swir-oobe-reload')){
        sessionStorage.setItem('swir-oobe-reload','1');
        location.reload();
        return new Promise(()=>{});
      }
      await new Promise(r=>setTimeout(r,60));
    }
    sessionStorage.removeItem('swir-oobe-reload');
    await window.SwirPlatform.ready;
  }

  async function waitForBoot(){
    const boot=$('#boot-screen');
    if(!boot)return;
    while(!boot.classList.contains('boot-hidden')) await new Promise(r=>setTimeout(r,100));
  }

  function safeDeviceName(v){
    return String(v||'').trim().replace(/[^A-Za-z0-9_-]+/g,'-').replace(/^-+|-+$/g,'').slice(0,24);
  }

  function preferredPreset(){
    const svc=i18n();
    if(!svc)return LOCALE_PRESETS[0];
    const available=new Set(svc.messageLocales?.()||[]);
    const activePack=svc.localeChain?.(svc.locale)?.find(candidate=>available.has(candidate))||svc.fallbackLocale||'en';
    return LOCALE_PRESETS.find(candidate=>svc.localeChain?.(candidate)?.includes(activePack))||LOCALE_PRESETS[0];
  }

  function localeDisplayName(locale){
    try{
      const svc=i18n();
      const parsed=new Intl.Locale(locale);
      const names=new Intl.DisplayNames([svc?.locale||'en'],{type:'language'});
      return `${names.of(parsed.language)||locale} — ${locale}`;
    }catch{return locale}
  }

  function populateLocaleOptions(select){
    const selected=preferredPreset();
    select.replaceChildren(...LOCALE_PRESETS.map(locale=>{
      const option=document.createElement('option');
      option.value=locale;
      option.textContent=localeDisplayName(locale);
      return option;
    }));
    select.value=selected;
  }

  function setStatus(status,key,className='oobe-status',vars){
    status.textContent=tr(key,vars);
    status.className=className;
  }

  function show(){
    if($('#swir-oobe'))return;
    const el=document.createElement('section');el.id='swir-oobe';el.innerHTML=`
      <div class="oobe-card">
        <div class="oobe-kicker" data-i18n="oobe.kicker">SWIR OS // FIRST BOOT</div>
        <div class="oobe-title" data-i18n="oobe.welcome">Welcome to SWIR OS</div>
        <p class="oobe-lead" data-i18n="oobe.lead">Set up this device.</p>
        <div class="oobe-progress"><span class="active"></span><span class="active"></span><span class="active"></span></div>
        <div class="oobe-grid">
          <div class="oobe-field"><label data-i18n="system.language">LANGUAGE</label><select id="oobe-locale" class="oobe-input" aria-label="Language"></select></div>
          <div class="oobe-field"><label data-i18n="oobe.deviceName">DEVICE NAME</label><input id="oobe-device" class="oobe-input" maxlength="24" value="SWIR-WEB"></div>
          <div class="oobe-field"><label data-i18n="oobe.profileName">PROFILE NAME</label><input id="oobe-user" class="oobe-input" maxlength="32" value="SWIR"></div>
          <div class="oobe-field"><label data-i18n="oobe.optionalPin">OPTIONAL LOCAL PIN</label><input id="oobe-pin" class="oobe-input" inputmode="numeric" autocomplete="new-password" data-i18n-placeholder="oobe.pinPlaceholder" placeholder="Leave empty for no PIN"></div>
          <div class="oobe-field"><label data-i18n="system.theme">COLOR CORE</label><div class="oobe-theme-grid"><button class="oobe-theme active" data-theme="blue" type="button">BLUE</button><button class="oobe-theme" data-theme="green" type="button">GREEN</button><button class="oobe-theme" data-theme="purple" type="button">PURPLE</button></div></div>
        </div>
        <div class="oobe-note"><div data-i18n="oobe.note.role">First profile role: Creator</div><div data-i18n="oobe.note.pin">Web Edition PIN is a convenience lock.</div><div data-i18n="oobe.note.chat">Chat server administration uses its own Admin Key.</div></div>
        <div class="oobe-actions"><div id="oobe-status" class="oobe-status" data-i18n="oobe.status.ready">READY TO CONFIGURE</div><button id="oobe-finish" class="oobe-btn" type="button" data-i18n="oobe.finish">FINISH SETUP & ENTER</button></div>
      </div>`;
    document.body.appendChild(el);

    const localeSelect=$('#oobe-locale',el);
    populateLocaleOptions(localeSelect);
    i18n()?.applyDocument?.(el);

    localeSelect.addEventListener('change',()=>{
      const svc=i18n();
      if(!svc)return;
      svc.setLocale(localeSelect.value);
      populateLocaleOptions(localeSelect);
      svc.applyDocument?.(el);
    });

    let theme='blue';
    el.addEventListener('click',e=>{const b=e.target.closest('[data-theme]');if(!b)return;theme=b.dataset.theme;el.querySelectorAll('[data-theme]').forEach(x=>x.classList.toggle('active',x===b))});
    $('#oobe-finish',el).addEventListener('click',async()=>{
      const status=$('#oobe-status',el),name=$('#oobe-user',el).value.trim(),device=safeDeviceName($('#oobe-device',el).value),pin=$('#oobe-pin',el).value;
      if(name.length<2){setStatus(status,'oobe.error.profileShort','oobe-status bad');return}
      if(device.length<2){setStatus(status,'oobe.error.deviceShort','oobe-status bad');return}
      setStatus(status,'oobe.status.applying');
      try{
        const p=window.SwirPlatform;const current=await p.identity.active();
        await p.identity.update(current.id,{name,role:'creator',avatar:name.slice(0,2).toUpperCase(),pin});
        await p.identity.setActive(current.id);
        await p.settings.set('device.name',device.toUpperCase());
        await p.settings.set('device.createdAt',Date.now());
        await p.settings.set('system.language',i18n()?.locale||localeSelect.value);
        await p.settings.set('oobe.complete',true);
        await p.settings.userSet(current.id,'theme',theme);
        window.SwirOS?.setTheme?.(theme);
        localStorage.setItem('swir-theme',theme);
        setStatus(status,'oobe.status.configured','oobe-status ok');
        window.postMessage({type:'SWIR_IDENTITY_CHANGED'},location.origin);
        setTimeout(()=>{el.remove();const lock=$('#lock-screen');lock?.classList.add('visible');lock?.setAttribute('aria-hidden','false')},350);
      }catch(err){setStatus(status,'oobe.error.setupFailed','oobe-status bad',{message:err?.message||String(err)})}
    });
  }

  async function init(){
    await waitForPlatform();
    const done=await window.SwirPlatform.settings.get('oobe.complete',false);
    if(done)return;
    await waitForBoot();show();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
