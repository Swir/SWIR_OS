/* SWIR OS 1.7 — verified installable Web widget host */
(() => {
  'use strict';

  const WIDGETS = Object.freeze({
    'widget-clock': Object.freeze({ packageId: 'swir.widget.clock', entry: './swir-widget-clock.html', renderer: 'clock' }),
    'widget-system': Object.freeze({ packageId: 'swir.widget.system', entry: './swir-widget-system.html', renderer: 'system' })
  });
  const HOST_ID = 'swir-package-widgets';
  const STYLE_ID = 'swir-package-widgets-style';
  let clockTimer = 0;

  const catalog = () => Array.isArray(globalThis.SWIR_PACKAGE_CATALOG) ? globalThis.SWIR_PACKAGE_CATALOG : [];
  const platform = () => globalThis.SwirPlatform || null;

  function descriptorFor(pkg) {
    if (!pkg || typeof pkg !== 'object') return null;
    const descriptor = WIDGETS[pkg.id];
    if (!descriptor) return null;
    if (pkg.schema !== 'swir.app/1.0' || pkg.category !== 'Widgets' || pkg.type !== 'iframe' || pkg.desktop !== false) return null;
    if (pkg.packageId !== descriptor.packageId || pkg.entry !== descriptor.entry) return null;
    const editions = Array.isArray(pkg.compatibility?.editions) ? pkg.compatibility.editions.map(value => String(value).toUpperCase()) : [];
    if (editions.length !== 1 || editions[0] !== 'WEB') return null;
    return descriptor;
  }

  function verifiedInstall(item) {
    return !!item && item.installed !== false && item.kind === 'swir-app-package' && item.verification?.officialCatalog === true;
  }

  function resolveInstalledWidgets(installed = [], available = catalog()) {
    const verifiedIds = new Set((Array.isArray(installed) ? installed : []).filter(verifiedInstall).map(item => item.id));
    return (Array.isArray(available) ? available : [])
      .filter(pkg => verifiedIds.has(pkg.id) && descriptorFor(pkg))
      .map(pkg => Object.freeze({ package: pkg, descriptor: descriptorFor(pkg) }));
  }

  async function installedWidgets() {
    const api = platform();
    if (!api?.packages?.list) return [];
    try { return resolveInstalledWidgets(await api.packages.list(), catalog()); }
    catch (_) { return []; }
  }

  function ensureStyle() {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${HOST_ID}{position:absolute;right:22px;top:270px;z-index:18;width:min(330px,calc(100vw - 44px));display:grid;gap:10px;pointer-events:auto}
      #${HOST_ID}[hidden]{display:none!important}
      .swir-package-widget{border:1px solid rgba(98,229,255,.2);border-radius:16px;background:linear-gradient(145deg,rgba(7,17,28,.94),rgba(2,5,10,.9));box-shadow:0 16px 48px rgba(0,0,0,.28),0 0 24px rgba(0,136,255,.06);padding:13px 14px;backdrop-filter:blur(14px);min-height:92px}
      .swir-package-widget-head{display:flex;align-items:center;justify-content:space-between;gap:10px;color:#8da8b8;font:700 9px/1.2 ui-monospace,Consolas,monospace;letter-spacing:.08em;text-transform:uppercase}
      .swir-package-widget-head strong{color:#62e5ff;font-size:10px;letter-spacing:.06em}
      .swir-package-widget-value{margin-top:8px;color:#f4faff;font:800 26px/1.05 system-ui,-apple-system,"Segoe UI",sans-serif;letter-spacing:-.03em}
      .swir-package-widget-sub{margin-top:6px;color:#8da8b8;font:500 10px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
      .swir-package-widget-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:9px}
      .swir-package-widget-stat{border:1px solid rgba(98,229,255,.11);border-radius:9px;background:rgba(255,255,255,.025);padding:7px;min-width:0}
      .swir-package-widget-stat strong{display:block;color:#f4faff;font:800 13px/1.1 ui-monospace,Consolas,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .swir-package-widget-stat span{display:block;margin-top:4px;color:#738e9e;font:700 7px/1.2 ui-monospace,Consolas,monospace;text-transform:uppercase}
      @media(max-width:900px){#${HOST_ID}{right:12px;top:auto;bottom:78px;width:min(310px,calc(100vw - 24px))}}
      @media(max-width:620px){#${HOST_ID}{display:none!important}}
    `;
    document.head.appendChild(style);
  }

  function ensureHost() {
    if (typeof document === 'undefined') return null;
    let host = document.getElementById(HOST_ID);
    if (host) return host;
    const shell = document.getElementById('os-shell');
    if (!shell) return null;
    host = document.createElement('section');
    host.id = HOST_ID;
    host.hidden = true;
    host.setAttribute('aria-label', 'Installed SWIR desktop widgets');
    host.setAttribute('aria-live', 'off');
    const windowLayer = document.getElementById('window-layer');
    if (windowLayer?.parentNode === shell) shell.insertBefore(host, windowLayer);
    else shell.appendChild(host);
    return host;
  }

  function text(parent, tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = String(value ?? '');
    parent.appendChild(node);
    return node;
  }

  function baseCard(pkg, label) {
    const card = document.createElement('article');
    card.className = 'swir-package-widget';
    card.dataset.widgetPackage = pkg.packageId;
    card.setAttribute('aria-label', pkg.name);
    const head = document.createElement('div');
    head.className = 'swir-package-widget-head';
    text(head, 'strong', '', pkg.name);
    text(head, 'span', '', label);
    card.appendChild(head);
    return card;
  }

  function renderClock(pkg) {
    const card = baseCard(pkg, 'Installed package');
    const value = text(card, 'div', 'swir-package-widget-value', '--:--');
    const sub = text(card, 'div', 'swir-package-widget-sub', 'Local time');
    const update = () => {
      const now = new Date();
      value.textContent = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(now);
      sub.textContent = new Intl.DateTimeFormat(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }).format(now);
    };
    update();
    return { card, update };
  }

  async function renderSystem(pkg) {
    const card = baseCard(pkg, 'Verified state');
    const info = (() => { try { return platform()?.system?.info?.() || {}; } catch (_) { return {}; } })();
    let installed = [];
    try { installed = await platform()?.packages?.list?.() || []; } catch (_) {}
    text(card, 'div', 'swir-package-widget-value', String(info.edition || 'WEB').toUpperCase());
    text(card, 'div', 'swir-package-widget-sub', 'Read-only runtime snapshot from SWIR Platform');
    const grid = document.createElement('div');
    grid.className = 'swir-package-widget-grid';
    const stats = [
      [info.version || '1.7', 'OS'],
      [info.platformApi || 2, 'Platform API'],
      [installed.filter(item => item?.installed !== false).length, 'Packages']
    ];
    for (const [value, label] of stats) {
      const stat = document.createElement('div');
      stat.className = 'swir-package-widget-stat';
      text(stat, 'strong', '', value);
      text(stat, 'span', '', label);
      grid.appendChild(stat);
    }
    card.appendChild(grid);
    return card;
  }

  async function render() {
    if (typeof document === 'undefined') return [];
    ensureStyle();
    const host = ensureHost();
    if (!host) return [];
    clearInterval(clockTimer);
    clockTimer = 0;
    host.replaceChildren();
    const widgets = await installedWidgets();
    const clockUpdates = [];
    for (const item of widgets) {
      if (item.descriptor.renderer === 'clock') {
        const clock = renderClock(item.package);
        host.appendChild(clock.card);
        clockUpdates.push(clock.update);
      } else if (item.descriptor.renderer === 'system') {
        host.appendChild(await renderSystem(item.package));
      }
    }
    host.hidden = widgets.length === 0;
    if (clockUpdates.length) clockTimer = setInterval(() => clockUpdates.forEach(update => update()), 1000);
    return widgets;
  }

  const api = Object.freeze({
    meta: Object.freeze({ name: 'SWIR Web Widgets', version: '1.0.0', model: 'verified-installable-packages' }),
    descriptorFor,
    verifiedInstall,
    resolveInstalledWidgets,
    installedWidgets,
    render
  });
  globalThis.SwirWidgets = api;

  if (typeof document !== 'undefined') {
    const init = () => render().catch(error => console.warn('[SWIR Widgets] render failed', error));
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
    else queueMicrotask(init);
    globalThis.addEventListener?.('swir:package-change', init);
  }
})();
