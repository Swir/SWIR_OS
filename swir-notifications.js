/* SWIR OS 1.7 — portable application notification service */
(() => {
  'use strict';

  const HISTORY_KEY = 'swir-app-notifications-v1';
  const SCHEMA_VERSION = 2;
  const MAX_HISTORY = 50;
  const MAX_SERIALIZED_BYTES = 128 * 1024;
  const MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
  const MAX_ACTIONS = 3;
  const ACTION_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,47}$/;

  let memoryHistory = [];
  let persistenceAdapter = null;

  const clampText = (value, max) => String(value == null ? '' : value).slice(0, max);
  const nowMs = () => Date.now();
  const catalog = () => Array.isArray(window.SWIR_PACKAGE_CATALOG) ? window.SWIR_PACKAGE_CATALOG : [];
  const manifest = id => catalog().find(x => x.id === id || x.packageId === id) || null;
  const installed = id => {
    try {
      const v = JSON.parse(localStorage.getItem('swir-installed-apps') || '[]');
      return Array.isArray(v) && v.includes(id);
    } catch {
      return false;
    }
  };

  async function allowed(appId) {
    if (appId === 'system' || appId === 'swir.system') return true;
    const pkg = manifest(appId);
    if (!pkg || !installed(pkg.id)) return false;
    if (!(pkg.permissions || []).includes('notifications')) return false;
    try {
      return (await window.SwirPlatform?.permissions?.get?.(pkg.id, 'notifications'))?.value === true;
    } catch {
      return false;
    }
  }

  function normalizeAction(action) {
    if (!action || typeof action !== 'object') return null;
    const id = clampText(action.id, 48);
    const label = clampText(action.label, 64);
    if (!ACTION_ID_RE.test(id) || !label) return null;
    const type = action.type === 'open-app' ? 'open-app' : 'event';
    const targetApp = type === 'open-app' ? clampText(action.targetApp || action.appId || '', 120) : '';
    if (type === 'open-app' && !targetApp) return null;
    return Object.freeze({ id, label, type, targetApp });
  }

  function normalizeActions(actions) {
    if (!Array.isArray(actions)) return [];
    const seen = new Set();
    const result = [];
    for (const raw of actions) {
      const action = normalizeAction(raw);
      if (!action || seen.has(action.id)) continue;
      seen.add(action.id);
      result.push(action);
      if (result.length >= MAX_ACTIONS) break;
    }
    return result;
  }

  function normalize(options = {}) {
    if (typeof options === 'string') options = { message: options };
    const legacyOpenApp = options.openApp ? clampText(options.openApp, 120) : '';
    const actions = normalizeActions(options.actions);
    if (legacyOpenApp && actions.length < MAX_ACTIONS && !actions.some(action => action.id === 'open')) {
      actions.push(Object.freeze({ id: 'open', label: 'Open', type: 'open-app', targetApp: legacyOpenApp }));
    }
    return {
      title: clampText(options.title || 'SWIR App', 80),
      message: clampText(options.message || 'Application event', 300),
      tag: clampText(options.tag || '', 64),
      priority: ['low', 'normal', 'high'].includes(options.priority) ? options.priority : 'normal',
      silent: options.silent === true,
      openApp: legacyOpenApp,
      actions
    };
  }

  function sanitizePersistedItem(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const time = new Date(raw.time || 0);
    const timeMs = time.getTime();
    if (!Number.isFinite(timeMs) || timeMs <= 0 || nowMs() - timeMs > MAX_AGE_MS || timeMs - nowMs() > 5 * 60 * 1000) return null;
    const id = clampText(raw.id, 96);
    const appId = clampText(raw.appId, 120);
    if (!id || !appId) return null;
    const normalized = normalize(raw);
    return {
      id,
      appId,
      packageId: clampText(raw.packageId || 'swir.system', 120),
      appName: clampText(raw.appName || 'SWIR OS', 80),
      ...normalized,
      time: time.toISOString()
    };
  }

  function sanitizeHistory(value) {
    const rows = Array.isArray(value)
      ? value
      : (value && value.version === SCHEMA_VERSION && Array.isArray(value.notifications) ? value.notifications : []);
    const result = [];
    const seenIds = new Set();
    for (const raw of rows) {
      const item = sanitizePersistedItem(raw);
      if (!item || seenIds.has(item.id)) continue;
      seenIds.add(item.id);
      result.push(item);
      if (result.length >= MAX_HISTORY) break;
    }
    return result;
  }

  const localStorageAdapter = Object.freeze({
    id: 'local-storage',
    load() {
      const raw = localStorage.getItem(HISTORY_KEY);
      if (!raw) return [];
      if (raw.length > MAX_SERIALIZED_BYTES) return [];
      return JSON.parse(raw);
    },
    save(envelope) {
      const serialized = JSON.stringify(envelope);
      if (serialized.length > MAX_SERIALIZED_BYTES) throw new Error('Notification history exceeds persistence limit');
      localStorage.setItem(HISTORY_KEY, serialized);
    }
  });

  function activeAdapter() {
    return persistenceAdapter || localStorageAdapter;
  }

  function loadInitialHistory() {
    try {
      const loaded = activeAdapter().load();
      if (loaded && typeof loaded.then === 'function') return memoryHistory.slice();
      memoryHistory = sanitizeHistory(loaded);
    } catch {
      // Keep a validated in-memory snapshot when storage is missing or corrupt.
    }
    return memoryHistory.slice();
  }

  function envelope(history) {
    return Object.freeze({ version: SCHEMA_VERSION, notifications: history.slice(0, MAX_HISTORY) });
  }

  async function persistHistory(history) {
    memoryHistory = sanitizeHistory(history);
    try {
      await activeAdapter().save(envelope(memoryHistory));
      return true;
    } catch {
      return false;
    }
  }

  async function hydrate() {
    try {
      const loaded = await activeAdapter().load();
      memoryHistory = sanitizeHistory(loaded);
    } catch {
      // Keep the last validated in-memory snapshot if the adapter is unavailable.
    }
    return memoryHistory.slice();
  }

  async function setPersistenceAdapter(adapter = null) {
    if (adapter !== null && (typeof adapter !== 'object' || typeof adapter.load !== 'function' || typeof adapter.save !== 'function')) {
      throw new TypeError('Notification persistence adapter requires load() and save()');
    }
    persistenceAdapter = adapter;
    return hydrate();
  }

  async function deliverNative(item) {
    const show = window.SWIR_NATIVE_HOST?.notifications?.show;
    if (typeof show !== 'function') return null;
    const actions = item.actions.map(({ id, label, type, targetApp }) => ({ id, label, type, targetApp }));
    return show(item.title, item.message, item.packageId, item.silent, actions);
  }

  async function send(appId, options = {}) {
    const pkg = manifest(appId);
    const id = pkg?.id || String(appId || '');
    if (!(await allowed(id))) throw new Error('Notification permission denied');
    const n = normalize(options);
    const item = {
      id: `ntf-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
      appId: id,
      packageId: pkg?.packageId || 'swir.system',
      appName: pkg?.name || 'SWIR OS',
      ...n,
      time: new Date().toISOString()
    };
    const nativeDelivery = await deliverNative(item);
    const history = memoryHistory.slice();
    if (item.tag) {
      const i = history.findIndex(x => x.appId === item.appId && x.tag === item.tag);
      if (i >= 0) history.splice(i, 1);
    }
    history.unshift(item);
    await persistHistory(history);
    window.dispatchEvent(new CustomEvent('swir:notification', { detail: { ...item, nativeDelivery } }));
    if (!nativeDelivery) window.SwirOS?.toast?.(item.title, item.message);
    return { ...item, nativeDelivery };
  }

  function list(appId = null) {
    const h = memoryHistory.slice();
    return appId ? h.filter(x => x.appId === appId) : h;
  }

  async function clear(appId = null) {
    const next = appId ? memoryHistory.filter(x => x.appId !== appId) : [];
    await persistHistory(next);
    window.dispatchEvent(new CustomEvent('swir:notifications-clear', { detail: { appId } }));
  }

  async function invokeAction(notificationId, actionId) {
    const item = memoryHistory.find(row => row.id === notificationId);
    if (!item) throw new Error('Notification not found');
    const action = item.actions.find(row => row.id === actionId);
    if (!action) throw new Error('Notification action not found');
    const detail = Object.freeze({
      notificationId: item.id,
      actionId: action.id,
      actionType: action.type,
      targetApp: action.targetApp,
      appId: item.appId,
      packageId: item.packageId
    });
    let nativeResult = null;
    const nativeInvoke = window.SWIR_NATIVE_HOST?.notifications?.invokeAction;
    if (typeof nativeInvoke === 'function') nativeResult = await nativeInvoke(detail);
    window.dispatchEvent(new CustomEvent('swir:notification-action', { detail }));
    return { ...detail, nativeResult };
  }

  // Load/migrate the bounded local snapshot once. Restoring history never invokes actions.
  loadInitialHistory();

  window.SwirNotifications = Object.freeze({
    send,
    list,
    clear,
    allowed,
    invokeAction,
    hydrate,
    setPersistenceAdapter,
    historyKey: HISTORY_KEY,
    schemaVersion: SCHEMA_VERSION,
    limits: Object.freeze({ history: MAX_HISTORY, actions: MAX_ACTIONS, serializedBytes: MAX_SERIALIZED_BYTES })
  });
})();
