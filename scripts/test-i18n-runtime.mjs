import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const storage = new Map();
const documentElement = { lang: '', dir: '', dataset: {} };
const document = {
  readyState: 'complete',
  documentElement,
  querySelectorAll: () => [],
  addEventListener: () => {}
};
const window = {
  dispatchEvent: () => true
};
class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
}

const context = vm.createContext({
  console,
  Intl,
  Map,
  Set,
  Object,
  Array,
  String,
  Number,
  Date,
  TypeError,
  RangeError,
  CustomEvent,
  document,
  window,
  navigator: { languages: ['zh-CN'], language: 'zh-CN' },
  localStorage: {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value))
  }
});

vm.runInContext(fs.readFileSync('swir-i18n.js', 'utf8'), context, { filename: 'swir-i18n.js' });
vm.runInContext(fs.readFileSync('swir-locale-packs.js', 'utf8'), context, { filename: 'swir-locale-packs.js' });

const i18n = window.SwirI18n;
assert(i18n, 'SwirI18n should be installed on window');
assert.equal(i18n.contract, 'swir.i18n/1.0');
assert.equal(i18n.fallbackLocale, 'en');
assert.equal(window.SwirLocalePackCatalog?.bundled, true);
assert.equal(i18n.messageLocales().length, 15, '15 core locale packs should be bundled');

assert(i18n.localeChain('zh-CN').includes('zh-Hans'), 'zh-CN must resolve through the Simplified Chinese script pack');
assert.equal(i18n.t('system.settings', null, { locale: 'zh-CN' }), '设置');
assert.equal(i18n.t('system.search', null, { locale: 'zh-SG' }), '搜索应用...');

assert(i18n.localeChain('no-NO').includes('nb'), 'legacy Norwegian no-NO must fall back to Bokmål');
assert.equal(i18n.t('system.settings', null, { locale: 'no-NO' }), 'Innstillinger');
assert.equal(i18n.t('system.settings', null, { locale: 'nb-NO' }), 'Innstillinger');

assert.equal(i18n.directionOf('ar-EG'), 'rtl');
assert.equal(i18n.directionOf('he-IL'), 'rtl');
assert.equal(i18n.directionOf('de-DE'), 'ltr');
i18n.setLocale('ar-EG', { persist: false });
assert.equal(documentElement.lang, 'ar-EG');
assert.equal(documentElement.dir, 'rtl');
assert.equal(i18n.t('system.controlCenter'), 'مركز التحكم');

i18n.setLocale('de-DE', { persist: false });
assert.equal(documentElement.dir, 'ltr');
assert.equal(i18n.t('system.notifications'), 'Benachrichtigungszentrale');

assert.equal(i18n.t('system.settings', null, { locale: 'eo' }), 'Settings', 'unsupported language must fail back to English');
assert.throws(() => i18n.setLocale('not_a_locale'), RangeError);

console.log('SWIR i18n runtime self-tests: OK — regional/script fallback, Norwegian alias, RTL and English fallback verified.');
