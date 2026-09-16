import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const requiredLocales=['en','pl','nb','de','es','fr','it','pt-BR','uk','ru','tr','ar','he','ja','zh-Hans'];
const requiredKeys=[
  'files.home','files.apps','files.documents','files.appData','files.trash','files.import','files.newFolder','files.newText','files.emptyTrash',
  'store.search','store.audit','store.installPackage','store.packageSpec','store.defaultApps','store.apply',
  'updates.title','updates.repository','updates.serviceWorker','updates.network','updates.cache','updates.desktopHost','updates.desktopFeed','updates.desktopPreparation','updates.desktopRestart','updates.openStore','updates.reloadSystem','updates.clearCache','updates.openGithub',
  'settings.save','settings.general','settings.languageRegion','settings.appearance','settings.audio','settings.session','settings.storage','settings.system','settings.deviceName','settings.systemLocale','settings.useDeviceLocale','settings.preview',
  'common.refresh','device.title','device.identity','device.saveHostname','device.copyReport','device.hardwareReport','device.nativeInventory',
  'network.title','network.nativeAdapters','network.profiles','network.createProfile','network.profileName','network.type','network.notes','network.addProfile'
];
const registered=new Map();
const context={window:{SwirI18n:{registerMessages(locale,messages){registered.set(locale,{...(registered.get(locale)||{}),...messages});}}}};
vm.createContext(context);
const localeFiles=['swir-app-locales-west.js','swir-app-locales-global.js','swir-app-locales-world.js','swir-app-locales-system.js'];
for(const file of localeFiles) vm.runInContext(fs.readFileSync(file,'utf8'),context,{filename:file});
assert.equal(context.window.SwirAppLocalePackCatalog?.contract,'swir.app-locale-packs/0.1');
assert.equal(context.window.SwirAppLocalePackCatalog?.bundled,true);
assert.equal(context.window.SwirAppLocalePackCatalog?.keyCount,requiredKeys.length);
assert.deepEqual([...registered.keys()].sort(),[...requiredLocales].sort());
assert.deepEqual([...context.window.SwirAppLocalePackCatalog.locales].sort(),[...requiredLocales].sort());
for(const locale of requiredLocales){
  const pack=registered.get(locale);
  assert(pack,`missing application locale ${locale}`);
  for(const key of requiredKeys) assert.equal(typeof pack[key]==='string'&&pack[key].trim().length>0,true,`${locale} missing ${key}`);
}
const helper=fs.readFileSync('swir-app-i18n.js','utf8');
for(const page of ['swir-files.html','swir-store.html','swir-updates.html','swir-settings.html','swir-device.html','swir-network.html']) assert(helper.includes(`'${page}'`),`helper missing ${page}`);
assert(helper.includes("contract:'swir.app-i18n/0.2'"),'application helper contract must be 0.2');
assert(helper.includes('parent.SwirI18n'),'application helper must consume the parent locale service');
assert(helper.includes('document.documentElement.dir'),'application helper must propagate RTL/LTR direction');
for(const marker of ['device.title','device.nativeInventory','network.title','network.addProfile']) assert(helper.includes(marker),`helper missing system binding ${marker}`);
const host=fs.readFileSync('swir-app-i18n-host.js','utf8');
assert(host.includes('/^swir-[a-z0-9-]+\\.html$/'),'host must only target root SWIR application pages');
assert(host.includes('MutationObserver'),'host must localize applications opened after shell boot');
const bootstrap=fs.readFileSync('swir-v11.js','utf8');
const order=[...localeFiles,'swir-app-i18n-host.js'].map(name=>bootstrap.indexOf(name));
assert(order.every(x=>x>=0)&&order.every((x,i)=>i===0||x>order[i-1]),'bundled locale packs must load before iframe localization host');
assert(bootstrap.includes('script.async = false'),'bootstrap must preserve deterministic locale/host load order');
const sw=fs.readFileSync('sw.js','utf8');
for(const file of [...localeFiles,'swir-app-i18n.js','swir-app-i18n-host.js']) assert(sw.includes(`./${file}`),`service worker must cache ${file}`);
assert(sw.includes('app-i18n-0.2.0'),'service worker cache version must advance for expanded application i18n');
console.log(`SWIR application i18n packs: ${requiredLocales.length} locales x ${requiredKeys.length} critical UI keys OK`);
