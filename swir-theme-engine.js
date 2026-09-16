/* SWIR Appearance Engine 1.0 — safe shell profile + accent runtime */
(() => {
  'use strict';

  const PROFILE_KEY = 'swir-theme-profile';
  const ACCENT_KEY = 'swir-theme';
  const DEFAULT_PROFILE = 'neon';
  const DEFAULT_ACCENT = 'blue';
  const ACCENTS = Object.freeze(['blue', 'green', 'purple']);
  const SAFE_TOKEN_KEYS = Object.freeze(new Set([
    '--bg-0', '--bg-1', '--bg-2', '--panel', '--panel-strong', '--panel-soft',
    '--line', '--line-strong', '--accent', '--accent-2', '--accent-soft', '--text',
    '--muted', '--success', '--warning', '--danger', '--shadow', '--radius',
    '--taskbar-h', '--topbar-h'
  ]));
  const FORBIDDEN_TOKEN_FRAGMENTS = /(?:url\s*\(|expression\s*\(|javascript:|@import|[;{}])/i;

  const BUILTIN = Object.freeze([
    Object.freeze({ id:'neon', label:'Neon Core', description:'SWIR signature neon shell with layered glass and luminous accents.', builtin:true }),
    Object.freeze({ id:'glass', label:'Crystal Glass', description:'More transparent panels, stronger blur and soft rounded chrome.', builtin:true }),
    Object.freeze({ id:'minimal', label:'Minimal Flow', description:'Reduced decoration, flatter surfaces and compact visual noise.', builtin:true }),
    Object.freeze({ id:'classic', label:'Classic Desktop', description:'Compact opaque desktop chrome with restrained motion and squared geometry.', builtin:true }),
    Object.freeze({ id:'contrast', label:'High Contrast', description:'Accessibility-first high contrast shell with strong focus and readable boundaries.', builtin:true, accessibility:true })
  ]);

  const customProfiles = new Map();
  let activeCustomTokenKeys = [];

  const css = `
html[data-swir-profile="glass"]{--panel:rgba(11,28,48,.58);--panel-strong:rgba(8,20,36,.78);--panel-soft:rgba(15,40,65,.5);--line:rgba(164,224,255,.22);--line-strong:rgba(167,229,255,.52);--radius:24px;--shadow:0 28px 100px rgba(0,0,0,.44)}
html[data-swir-profile="glass"] .os-window,html[data-swir-profile="glass"] .launcher,html[data-swir-profile="glass"] .v11-side-panel,html[data-swir-profile="glass"] .desktop-widget{backdrop-filter:blur(28px) saturate(1.22)}
html[data-swir-profile="minimal"]{--panel:rgba(5,13,24,.9);--panel-strong:rgba(4,10,19,.97);--panel-soft:rgba(8,18,30,.82);--line:rgba(255,255,255,.1);--line-strong:rgba(255,255,255,.2);--radius:10px;--shadow:none}
html[data-swir-profile="minimal"] .os-window,html[data-swir-profile="minimal"] .launcher,html[data-swir-profile="minimal"] .v11-side-panel,html[data-swir-profile="minimal"] .desktop-widget{backdrop-filter:none!important;box-shadow:none!important}
html[data-swir-profile="minimal"] .wallpaper-orb{opacity:.18}
html[data-swir-profile="classic"]{--panel:#18202b;--panel-strong:#111821;--panel-soft:#222d3a;--line:#435466;--line-strong:#6c8398;--radius:6px;--shadow:0 10px 28px rgba(0,0,0,.5);--taskbar-h:50px;--topbar-h:40px}
html[data-swir-profile="classic"] .os-window,html[data-swir-profile="classic"] .launcher,html[data-swir-profile="classic"] .v11-side-panel,html[data-swir-profile="classic"] .desktop-widget{backdrop-filter:none!important}
html[data-swir-profile="classic"] .window-titlebar,html[data-swir-profile="classic"] .taskbar,html[data-swir-profile="classic"] .topbar{background:var(--panel-strong)!important}
html[data-swir-profile="contrast"]{--bg-0:#000;--bg-1:#000;--bg-2:#090909;--panel:#000;--panel-strong:#000;--panel-soft:#050505;--line:#fff;--line-strong:#fff;--accent:#ffe600;--accent-2:#fff36a;--accent-soft:rgba(255,230,0,.18);--text:#fff;--muted:#e8e8e8;--success:#6dff9d;--warning:#ffe600;--danger:#ff718f;--shadow:0 0 0 2px #000;--radius:4px}
html[data-swir-profile="contrast"] *{text-shadow:none!important}
html[data-swir-profile="contrast"] button:focus-visible,html[data-swir-profile="contrast"] input:focus-visible,html[data-swir-profile="contrast"] select:focus-visible{outline:3px solid #ffe600!important;outline-offset:3px!important}
html[data-swir-profile="contrast"] .os-window,html[data-swir-profile="contrast"] .launcher,html[data-swir-profile="contrast"] .v11-side-panel,html[data-swir-profile="contrast"] .desktop-widget{backdrop-filter:none!important;border-width:2px!important}
`;

  function ensureStyle() {
    if (document.getElementById('swir-theme-engine-style')) return;
    const style = document.createElement('style');
    style.id = 'swir-theme-engine-style';
    style.textContent = css;
    document.head.appendChild(style);
  }

  function normalizeAccent(value) {
    const accent = String(value || '').trim().toLowerCase();
    return ACCENTS.includes(accent) ? accent : DEFAULT_ACCENT;
  }

  function profileIds() {
    return new Set([...BUILTIN.map(item => item.id), ...customProfiles.keys()]);
  }

  function normalizeProfile(value) {
    const profile = String(value || '').trim().toLowerCase();
    return profileIds().has(profile) ? profile : DEFAULT_PROFILE;
  }

  function sanitizePack(pack) {
    if (!pack || typeof pack !== 'object' || Array.isArray(pack)) throw new TypeError('Theme pack must be an object.');
    const id = String(pack.id || '').trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9._-]{1,47}$/.test(id)) throw new TypeError('Theme pack id must be 2-48 safe characters.');
    if (BUILTIN.some(item => item.id === id)) throw new TypeError('Built-in theme profile ids cannot be replaced.');
    const label = String(pack.label || '').trim();
    const description = String(pack.description || '').trim();
    if (!label || label.length > 48 || description.length > 180) throw new TypeError('Theme pack metadata is invalid.');
    if (pack.cssText || pack.script || pack.url || pack.entry) throw new TypeError('Theme packs cannot inject scripts, stylesheets or remote URLs.');
    const sourceTokens = pack.tokens && typeof pack.tokens === 'object' && !Array.isArray(pack.tokens) ? pack.tokens : {};
    const tokens = {};
    for (const [key, raw] of Object.entries(sourceTokens)) {
      if (!SAFE_TOKEN_KEYS.has(key)) throw new TypeError(`Theme token is not allowlisted: ${key}`);
      const value = String(raw ?? '').trim();
      if (!value || value.length > 96 || FORBIDDEN_TOKEN_FRAGMENTS.test(value)) throw new TypeError(`Theme token value is unsafe: ${key}`);
      tokens[key] = value;
    }
    if (!Object.keys(tokens).length) throw new TypeError('Theme pack must provide at least one safe design token.');
    return Object.freeze({ id, label, description, builtin:false, tokens:Object.freeze(tokens) });
  }

  function clearCustomTokens() {
    const root = document.documentElement;
    for (const key of activeCustomTokenKeys) root.style.removeProperty(key);
    activeCustomTokenKeys = [];
  }

  function applyCustomTokens(profile) {
    clearCustomTokens();
    const pack = customProfiles.get(profile);
    if (!pack) return;
    for (const [key, value] of Object.entries(pack.tokens)) document.documentElement.style.setProperty(key, value);
    activeCustomTokenKeys = Object.keys(pack.tokens);
  }

  function snapshot() {
    const profile = normalizeProfile(document.documentElement.dataset.swirProfile || localStorage.getItem(PROFILE_KEY));
    const accent = normalizeAccent(document.documentElement.dataset.theme || localStorage.getItem(ACCENT_KEY));
    const metadata = BUILTIN.find(item => item.id === profile) || customProfiles.get(profile) || BUILTIN[0];
    return Object.freeze({ schema:'swir.theme-state/1.0', profile, accent, label:metadata.label, builtin:metadata.builtin === true });
  }

  function apply(profileValue, accentValue, persist = true) {
    ensureStyle();
    const profile = normalizeProfile(profileValue);
    const accent = normalizeAccent(accentValue);
    document.documentElement.dataset.swirProfile = profile;
    document.documentElement.dataset.theme = accent;
    applyCustomTokens(profile);
    if (persist) {
      localStorage.setItem(PROFILE_KEY, profile);
      localStorage.setItem(ACCENT_KEY, accent);
    }
    const state = snapshot();
    window.dispatchEvent(new CustomEvent('swir:theme-change', { detail:state }));
    return state;
  }

  function setProfile(profile) {
    return apply(profile, document.documentElement.dataset.theme || localStorage.getItem(ACCENT_KEY), true);
  }

  function setAccent(accent) {
    return apply(document.documentElement.dataset.swirProfile || localStorage.getItem(PROFILE_KEY), accent, true);
  }

  function reset() {
    return apply(DEFAULT_PROFILE, DEFAULT_ACCENT, true);
  }

  function registerPack(pack) {
    const safe = sanitizePack(pack);
    customProfiles.set(safe.id, safe);
    window.dispatchEvent(new CustomEvent('swir:theme-catalog-change', { detail:Object.freeze({ id:safe.id, action:'registered' }) }));
    return safe;
  }

  function unregisterPack(id) {
    const key = String(id || '').trim().toLowerCase();
    if (!customProfiles.has(key)) return false;
    const wasActive = snapshot().profile === key;
    customProfiles.delete(key);
    if (wasActive) reset();
    window.dispatchEvent(new CustomEvent('swir:theme-catalog-change', { detail:Object.freeze({ id:key, action:'unregistered' }) }));
    return true;
  }

  function profiles() {
    return Object.freeze([...BUILTIN, ...customProfiles.values()].map(item => Object.freeze({
      id:item.id, label:item.label, description:item.description, builtin:item.builtin === true, accessibility:item.accessibility === true
    })));
  }

  const api = Object.freeze({
    schema:'swir.theme-engine/1.0',
    accents:ACCENTS,
    profiles,
    state:snapshot,
    apply:(profile, accent) => apply(profile, accent, true),
    setProfile,
    setAccent,
    reset,
    registerPack,
    unregisterPack,
    safeTokenKeys:Object.freeze([...SAFE_TOKEN_KEYS])
  });

  window.SwirThemeEngine = api;
  apply(localStorage.getItem(PROFILE_KEY) || DEFAULT_PROFILE, localStorage.getItem(ACCENT_KEY) || DEFAULT_ACCENT, false);
})();
