import fs from 'node:fs';

const read = path => fs.readFileSync(path, 'utf8');
const i18n = read('swir-i18n.js');
const localePacks = read('swir-locale-packs.js');
const index = read('index.html');
const manifest = read('manifest.webmanifest');
const sw = read('sw.js');
const stage = read('desktop/windows/stage-desktop-runtime.ps1');
const settings = read('swir-settings.html');
const sdk = read('swir-sdk.js');
const bridgeHost = read('swir-app-bridge-host.js');
const bridgeClient = read('swir-app-bridge.js');
const runtimeSelfTest = read('scripts/test-i18n-runtime.mjs');

const fail = message => { throw new Error(`SWIR_I18N_CONTRACT: ${message}`); };

if (!i18n.includes("const CONTRACT='swir.i18n/1.0'")) fail('missing swir.i18n/1.0 contract marker');
if (!i18n.includes("const VERSION='1.0.0'")) fail('unexpected locale runtime version');
for (const api of ['setLocale','registerMessages','formatDate','formatNumber','formatCurrency','formatRelativeTime','formatList']) {
  if (!i18n.includes(api)) fail(`missing required API: ${api}`);
}
if (!i18n.includes('Intl.getCanonicalLocales')) fail('BCP-47 canonicalization is missing');
if (!i18n.includes('Intl.Locale')) fail('Intl.Locale support is missing');
if (!i18n.includes('.maximize()')) fail('likely-script fallback for regional locale matching is missing');
if (!i18n.includes("LANGUAGE_ALIASES=Object.freeze({no:'nb'})")) fail('legacy Norwegian language alias is missing from runtime matching');
if (!i18n.includes("document.documentElement.dir=directionOf(canonical)")) fail('document RTL/LTR direction propagation is missing');
if (!i18n.includes("const FALLBACK_LOCALE='en'")) fail('English fallback locale must remain explicit');

if (!localePacks.includes("contract:'swir.locale-packs/1.0'")) fail('bundled locale pack contract missing');
if (!localePacks.includes('bundled:true')) fail('locale pack catalog must declare bundled delivery');
for (const locale of ['de','es','fr','it','pt-BR','uk','ru','tr','ar','he','ja','zh-Hans']) {
  const quotedSingle = `'${locale}'`;
  const unquoted = `${locale}:`;
  if (!localePacks.includes(quotedSingle) && !localePacks.includes(unquoted)) fail(`bundled core locale pack missing: ${locale}`);
}
for (const key of ['system.language','system.settings','system.search','system.notifications','system.controlCenter','system.installApp','system.update','system.restart','system.close']) {
  const occurrences = localePacks.split(`'${key}'`).length - 1;
  if (occurrences < 12) fail(`core translation coverage is incomplete for ${key}: ${occurrences}/12 extension packs`);
}
if (!i18n.includes("'ar'") || !i18n.includes("'he'")) fail('RTL language allowlist must include Arabic and Hebrew');

for (const marker of ["localeChain('zh-CN')", "localeChain('no-NO')", "directionOf('ar-EG')", "locale: 'eo'"]) {
  if (!runtimeSelfTest.includes(marker)) fail(`executable locale runtime coverage missing: ${marker}`);
}

const i18nScript = index.indexOf('<script src="./swir-i18n.js"></script>');
const packsScript = index.indexOf('<script src="./swir-locale-packs.js"></script>');
const platformScript = index.indexOf('<script src="./swir-platform.js"></script>');
if (i18nScript < 0) fail('index.html does not load swir-i18n.js');
if (packsScript < 0) fail('index.html does not load bundled locale packs');
if (!(i18nScript < packsScript && packsScript < platformScript)) fail('locale runtime and bundled packs must load before platform runtime');
if (!index.includes('data-i18n-placeholder="system.search"')) fail('shell search is not connected to i18n');
if (!index.includes('data-i18n="system.notifications"')) fail('notification center shell label is not connected to i18n');
if (!index.includes('data-i18n="system.controlCenter"')) fail('control center shell label is not connected to i18n');
if (!sw.includes("'./swir-i18n.js'") || !sw.includes("'./swir-locale-packs.js'")) fail('offline cache does not include complete locale runtime');
if (!stage.includes("'.js'")) fail('Desktop runtime staging must include JavaScript locale packs');

for (const marker of ['Language & Region','SYSTEM LOCALE','Intl.getCanonicalLocales','system.language','system.region','setLocale?.(canonical)']) {
  if (!settings.includes(marker)) fail(`System Settings locale integration missing: ${marker}`);
}
if (!settings.includes("if(!canonical){show('INVALID BCP-47 LOCALE")) fail('System Settings must fail closed on invalid locale');
if (!settings.includes("if(v==='no')return'nb-NO'")) fail('legacy Norwegian locale migration is missing');

for (const marker of ['locale: Object.freeze','localeInfo','localeTranslate','formatCurrency:localeCurrency']) {
  if (!sdk.includes(marker)) fail(`App SDK locale surface missing: ${marker}`);
}
for (const method of ['locale.info','locale.translate','locale.formatDate','locale.formatNumber','locale.formatCurrency','locale.formatRelativeTime','locale.formatList']) {
  if (!bridgeHost.includes(`case '${method}'`)) fail(`App Bridge host locale method missing: ${method}`);
  if (!bridgeClient.includes(`'${method}'`)) fail(`App Bridge client locale method missing: ${method}`);
}
if (bridgeHost.includes("case 'locale.set'") || bridgeClient.includes("'locale.set'")) fail('isolated applications must not be able to mutate system locale through the read-only bridge');

if (!sdk.includes("version: '1.6.1'")) fail('App SDK runtime version must be 1.6.1');
if (!index.includes('APP SDK: 1.6.1') || index.includes('App SDK 1.3')) fail('shell SDK version is stale');
if (!manifest.includes('SWIR App SDK 1.6.1') || manifest.includes('SWIR App SDK 1.3')) fail('PWA manifest SDK version is stale');

console.log('SWIR i18n contract OK: BCP-47 core, script/alias matching, English fallback, RTL, 12 bundled extension locale packs, shell bindings, offline cache, Desktop staging and SDK 1.6.1 consistency are wired.');
