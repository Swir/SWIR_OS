/* SWIR Desktop Update User Policy 1.0 — user intent only; never alters release trust */
(() => {
  'use strict';

  const SCHEMA = 'swir.desktop-update-user-policy/1.0';
  const KEY = 'swir-desktop-update-user-policy-v1';
  const SESSION_KEY = 'swir-desktop-update-startup-run-v1';
  const MODES = Object.freeze(['automatic', 'notify', 'manual']);
  const DEFAULT_MODE = 'notify';
  let startupRequest = null;
  let observer = null;

  function sanitizeMode(value) {
    const mode = String(value || '').trim().toLowerCase();
    return MODES.includes(mode) ? mode : DEFAULT_MODE;
  }

  function readStored() {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (raw && raw.schema === SCHEMA) return { schema:SCHEMA, mode:sanitizeMode(raw.mode), updatedAt:String(raw.updatedAt || '') };
    } catch {}
    return { schema:SCHEMA, mode:DEFAULT_MODE, updatedAt:'' };
  }

  function state() {
    const stored = readStored();
    return Object.freeze({
      schema: SCHEMA,
      mode: stored.mode,
      updatedAt: stored.updatedAt,
      desktop: isDesktop(),
      semantics: Object.freeze({
        automatic: 'signed-check-and-prepare-no-restart',
        notify: 'signed-check-only',
        manual: 'user-initiated-only'
      })
    });
  }

  function setMode(value) {
    const mode = sanitizeMode(value);
    const record = { schema:SCHEMA, mode, updatedAt:new Date().toISOString() };
    localStorage.setItem(KEY, JSON.stringify(record));
    window.dispatchEvent(new CustomEvent('swir:update-policy-change', { detail:Object.freeze({ ...record, desktop:isDesktop() }) }));
    return state();
  }

  function isDesktop() {
    const host = window.SWIR_NATIVE_HOST;
    return !!host
      && String(host.edition || '').toUpperCase() === 'DESKTOP'
      && host.features?.nativeUpdateBridge === true
      && host.features?.nativeUpdatePreparation === true;
  }

  function updateWindow() {
    return document.querySelector('.os-window[data-window="updates"]');
  }

  function updateFrame() {
    const frame = updateWindow()?.querySelector('iframe');
    if (!(frame instanceof HTMLIFrameElement)) return null;
    try {
      const url = new URL(frame.src, location.href);
      if (url.origin !== location.origin || url.pathname !== '/swir-updates.html') return null;
    } catch { return null; }
    return frame;
  }

  function injectFrameController(frame) {
    if (!(frame instanceof HTMLIFrameElement)) return false;
    let doc;
    try { doc = frame.contentDocument; } catch { return false; }
    if (!doc?.head) return false;
    if (doc.getElementById('swir-update-policy-frame-script')) return true;
    const script = doc.createElement('script');
    script.id = 'swir-update-policy-frame-script';
    script.src = './swir-update-policy-frame.js?v=1.0.0';
    script.async = false;
    doc.head.appendChild(script);
    return true;
  }

  function attachToFrame(frame) {
    if (!(frame instanceof HTMLIFrameElement)) return;
    const install = () => injectFrameController(frame);
    frame.addEventListener('load', install, { passive:true });
    if (frame.contentDocument?.readyState === 'interactive' || frame.contentDocument?.readyState === 'complete') install();
  }

  function discoverFrames() {
    const frame = updateFrame();
    if (frame) attachToFrame(frame);
  }

  function ensureObserver() {
    if (observer || !document.documentElement) return;
    observer = new MutationObserver(discoverFrames);
    observer.observe(document.documentElement, { childList:true, subtree:true });
    discoverFrames();
  }

  function minimizeBackgroundWindow() {
    const win = updateWindow();
    if (!win) return false;
    win.dataset.swirBackgroundUpdate = '1';
    if (!win.classList.contains('minimized')) {
      const button = win.querySelector('.window-control.minimize');
      if (button instanceof HTMLElement) button.click();
      else win.classList.add('minimized');
    }
    return true;
  }

  function closeHiddenBackgroundWindow() {
    const win = updateWindow();
    if (!win || win.dataset.swirBackgroundUpdate !== '1' || !win.classList.contains('minimized')) return false;
    try { window.SwirOS?.close?.('updates'); return true; } catch { return false; }
  }

  function claimStartupRequest() {
    const request = startupRequest;
    startupRequest = null;
    return request ? Object.freeze({ ...request }) : null;
  }

  function report(detail = {}) {
    const status = String(detail.status || 'unknown');
    const version = String(detail.targetVersion || '').trim();
    let message = '';
    if (status === 'current') message = 'SWIR OS Desktop is current.';
    else if (status === 'available') message = `SWIR OS Desktop ${version || 'update'} is available. Open Update Center to download it.`;
    else if (status === 'prepared') message = `SWIR OS Desktop ${version || 'update'} is verified and prepared. Restart when you are ready.`;
    else if (status === 'failed') message = `Desktop update ${detail.stage || 'check'} was blocked: ${detail.code || 'unknown error'}.`;
    else return false;
    try { window.SwirOS?.toast?.('Update Center', message); } catch {}
    window.dispatchEvent(new CustomEvent('swir:update-policy-result', { detail:Object.freeze({ ...detail, status }) }));
    if (status === 'current' || status === 'available' || status === 'prepared' || status === 'failed') {
      setTimeout(closeHiddenBackgroundWindow, 600);
    }
    return true;
  }

  function requestStartupCheck() {
    if (!isDesktop() || !window.SwirOS?.open) return false;
    const policy = state();
    if (policy.mode === 'manual') return false;
    if (sessionStorage.getItem(SESSION_KEY) === 'done') return false;
    sessionStorage.setItem(SESSION_KEY, 'done');
    startupRequest = Object.freeze({
      schema: 'swir.desktop-update-startup-request/1.0',
      id: `startup-${Date.now().toString(36)}`,
      mode: policy.mode,
      createdAt: new Date().toISOString()
    });
    window.SwirOS.open('updates');
    let attempts = 0;
    const settle = () => {
      attempts++;
      const frame = updateFrame();
      if (frame) {
        attachToFrame(frame);
        minimizeBackgroundWindow();
        return;
      }
      if (attempts < 30) setTimeout(settle, 100);
    };
    setTimeout(settle, 0);
    return true;
  }

  const api = Object.freeze({
    schema: SCHEMA,
    modes: MODES,
    state,
    setMode,
    requestStartupCheck,
    claimStartupRequest,
    report,
    isDesktop
  });
  window.SwirUpdatePolicy = api;

  function boot() {
    ensureObserver();
    let attempts = 0;
    const waitForShell = () => {
      attempts++;
      if (window.SwirOS?.open) {
        requestStartupCheck();
        return;
      }
      if (attempts < 100) setTimeout(waitForShell, 100);
    };
    waitForShell();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once:true });
  else boot();
})();