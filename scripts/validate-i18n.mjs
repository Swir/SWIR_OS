import fs from 'node:fs';

const read = path => fs.readFileSync(path, 'utf8');
const i18n = read('swir-i18n.js');
const localePacks = read('swir-locale-packs.js');
const oobe = read('swir-oobe.js');
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

if (!localePacks.includes("contract:'swir.locale-packs/1.1'")) fail('bundled locale pack contract 1.1 missing');
if (!localePacks.includes('bundled:true')) fail('locale pack catalog must declare bundled delivery');
if (!localePacks.includes('firstBootLocalized:true')) fail('locale pack catalog must declare localized first boot');
for (const locale of ['de','es','fr','it','pt-BR','uk','ru','tr','ar','he','ja','zh-Hans']) {
  const quotedSingle = `'${locale}'`;
  const unquoted = `${locale}:`;
  if (!localePacks.includes(quotedSingle) && !localePacks.includes(unquoted)) fail(`bundled core locale pack missing: ${locale}`);
}
for (const key of ['system.language','system.settings','system.search','system.notifications','system.controlCenter','system.installApp','system.update','system.restart','system.close']) {
  const occurrences = localePacks.split(`'${key}'`).length - 1;
  if (occurrences < 12) fail(`core translation coverage is incomplete for ${key}: ${occurrences}/12 extension packs`);
}
for (const key of ['oobe.welcome','oobe.lead','oobe.deviceName','oobe.profileName','oobe.optionalPin','oobe.finish','oobe.status.ready','oobe.status.configured','oobe.error.profileShort','oobe.error.deviceShort','oobe.error.setupFailed']) {
  const occurrences = localePacks.split(`'${key}'`).length - 1;
  if (occurrences < 15) fail(`first-boot translation coverage is incomplete for ${key}: ${occurrences}/15 bundled locales`);
}
if (!i18n.includes("'ar'") || !i18n.includes("'he'")) fail('RTL language allowlist must include Arabic and Hebrew');

for (const marker of ["localeChain('zh-CN')", "localeChain('no-NO')", "directionOf('ar-EG')", "locale: 'eo'", "firstBootLocales = ['en','pl','nb'", "i18n.t('oobe.welcome')"]) {
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
if (!sw.includes("'./swir-i18n.js'") || !sw.includes("'./swir-locale-packs.js'") || !sw.includes("'./swir-oobe.js'")) fail('offline cache does not include complete first-boot locale runtime');
if (!sw.includes('locales-1.1.0')) fail('service-worker locale cache version must be bumped for first-boot translations');
if (!stage.includes("'.js'")) fail('Desktop runtime staging must include JavaScript locale packs');

for (const marker of ['LOCALE_PRESETS=Object.freeze','data-i18n="oobe.welcome"','data-i18n="oobe.deviceName"','data-i18n-placeholder="oobe.pinPlaceholder"',"p.settings.set('system.language'",'Intl.DisplayNames','svc.setLocale(localeSelect.value)']) {
  if (!oobe.includes(marker)) fail(`localized OOBE integration missing: ${marker}`);
}
if (oobe.includes("meta?.version!=='1.4.0'")) fail('OOBE still contains stale version-specific reload logic');

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

console.log('SWIR i18n contract OK: BCP-47 core, 15 bundled first-boot locales, regional/script fallback, English fallback, RTL, localized OOBE, offline cache, Desktop staging and SDK 1.6.1 consistency are wired.');
