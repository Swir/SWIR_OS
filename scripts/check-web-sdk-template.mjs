import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const exampleDir = path.join(root, 'examples', 'swir-app-template');
const manifestPath = path.join(exampleDir, 'app.json');
const htmlPath = path.join(exampleDir, 'index.html');
const appPath = path.join(exampleDir, 'app.js');
const iconPath = path.join(exampleDir, 'icon.svg');
const packageContractPath = path.join(root, 'SWIR-APP-PACKAGE-1.0.md');
const sdkPath = path.join(root, 'swir-sdk.js');
const bridgeHostPath = path.join(root, 'swir-app-bridge-host.js');

function fail(message) {
  console.error(`WEB SDK TEMPLATE FAIL: ${message}`);
  process.exit(1);
}

function read(file) {
  try { return fs.readFileSync(file, 'utf8'); }
  catch (error) { fail(`cannot read ${path.relative(root, file)}: ${error.message}`); }
}

function compareVersions(a, b) {
  const parts = value => String(value).replace(/^v/i, '').split(/[.+-]/)[0].split('.').map(v => Number.parseInt(v, 10) || 0);
  const aa = parts(a), bb = parts(b), length = Math.max(aa.length, bb.length, 3);
  for (let i = 0; i < length; i++) {
    if ((aa[i] || 0) > (bb[i] || 0)) return 1;
    if ((aa[i] || 0) < (bb[i] || 0)) return -1;
  }
  return 0;
}

let manifest;
try { manifest = JSON.parse(read(manifestPath)); }
catch (error) { fail(`app.json is not valid JSON: ${error.message}`); }

for (const field of ['schema', 'id', 'packageId', 'name', 'version', 'author', 'type', 'entry']) {
  if (typeof manifest[field] !== 'string' || !manifest[field].trim()) fail(`manifest missing required string field: ${field}`);
}
if (manifest.schema !== 'swir.app/1.0') fail(`unexpected manifest schema: ${manifest.schema}`);
if (manifest.type !== 'iframe') fail('starter must use the iframe package type');
if (!/^[a-zA-Z0-9._-]{1,128}$/.test(manifest.id)) fail('invalid app id');
if (!/^[a-zA-Z0-9._-]{1,128}$/.test(manifest.packageId)) fail('invalid packageId');
if (manifest.packageId.startsWith('swir.')) fail('developer starter must not consume the reserved swir.* namespace');

const expectedEntry = './examples/swir-app-template/index.html';
if (manifest.entry !== expectedEntry) fail(`entry must remain ${expectedEntry}`);
const resolvedEntry = path.resolve(root, manifest.entry.replace(/^\.\//, ''));
if (resolvedEntry !== htmlPath || !fs.existsSync(resolvedEntry)) fail('manifest entry does not resolve to the starter index.html');

const expectedIcon = './examples/swir-app-template/icon.svg';
if (manifest.icon !== expectedIcon) fail(`icon must remain the local starter asset ${expectedIcon}`);
if (!fs.existsSync(iconPath)) fail('local starter icon is missing');

if (!Array.isArray(manifest.permissions) || manifest.permissions.length !== 1 || manifest.permissions[0] !== 'storage') {
  fail('starter must remain least-privilege and declare only storage');
}
if (!Array.isArray(manifest.associations) || manifest.associations.length !== 0) fail('starter must not claim file associations');
if (!Array.isArray(manifest.dependencies) || manifest.dependencies.length !== 0) fail('starter dependencies must remain empty');
if (!Array.isArray(manifest.optionalDependencies) || manifest.optionalDependencies.length !== 0) fail('starter optionalDependencies must remain empty');
if (!/^SWIR:\/\/APPDATA\/[A-Z0-9_-]+$/.test(String(manifest.appData || ''))) fail('starter must use a bounded SWIR app-data namespace');

const compatibility = manifest.compatibility || {};
if (compatibility.minOS !== '1.7.0') fail('starter minOS must match the current 1.7 resolver baseline');
if (compatibility.platformApi !== 2) fail('starter must target Platform API 2');
if (!Array.isArray(compatibility.editions) || compatibility.editions.length !== 1 || compatibility.editions[0] !== 'WEB') {
  fail('starter must remain explicitly Web Edition only');
}

const sdkSource = read(sdkPath);
const sdkVersion = sdkSource.match(/meta:\s*Object\.freeze\(\{\s*name:\s*'SWIR App SDK',\s*version:\s*'([^']+)'/)?.[1];
if (!sdkVersion) fail('cannot derive shipping SWIR App SDK version from swir-sdk.js');
if (compareVersions(sdkVersion, compatibility.minSDK) < 0) fail(`starter requires SDK ${compatibility.minSDK}, shipping SDK is ${sdkVersion}`);
if (compatibility.minSDK !== sdkVersion) fail(`starter minSDK drift: expected shipping SDK ${sdkVersion}, got ${compatibility.minSDK}`);

const packageContract = read(packageContractPath);
for (const permission of manifest.permissions) {
  if (!packageContract.includes(`- \`${permission}\``)) fail(`permission is not documented in SWIR App Package 1.0: ${permission}`);
}
if (!packageContract.includes('Official SWIR packages use the `swir.*` namespace.')) fail('reserved namespace rule missing from package contract');
if (!packageContract.includes('Arbitrary remote JavaScript is not treated as a trusted SWIR package.')) fail('same-origin Web trust rule missing from package contract');

const html = read(htmlPath);
for (const expected of [
  'src="../../swir-app-bridge.js"',
  `data-swir-package="${manifest.packageId}"`,
  `data-swir-app="${manifest.id}"`,
  'src="./app.js"'
]) {
  if (!html.includes(expected)) fail(`index.html missing required bridge binding: ${expected}`);
}
if (/\b(?:src|href)=["']https?:\/\//i.test(html)) fail('starter HTML must not load remote assets');
if (!html.includes('aria-live=') || !html.includes('role="status"')) fail('starter must preserve its accessible live status surface');

const app = read(appPath);
for (const expected of [
  'window.SwirAppBridge',
  'bridge.sdk.bridge.info()',
  'bridge.sdk.locale.info()',
  'bridge.sdk.locale.formatNumber(',
  'bridge.storage.get(',
  'bridge.storage.set(',
  'bridge.storage.remove('
]) {
  if (!app.includes(expected)) fail(`app.js missing SDK example: ${expected}`);
}
for (const forbidden of [
  /\blocalStorage\b/,
  /\bindexedDB\b/,
  /\bfetch\s*\(/,
  /\bXMLHttpRequest\b/,
  /\bWebSocket\b/,
  /\bparent\.SwirPlatform\b/,
  /\bwindow\.SwirPlatform\b/
]) {
  if (forbidden.test(app)) fail(`app.js bypasses the portable bridge: ${forbidden}`);
}

const bridgeHost = read(bridgeHostPath);
for (const securityMarker of [
  "if (!pkg) throw bridgeError('UNKNOWN_PACKAGE'",
  "throw bridgeError('IDENTITY_MISMATCH'",
  "await requireAnyPermission(pkg, ['storage', 'files.write'])",
  "await requireAnyPermission(pkg, ['storage', 'files.read'])"
]) {
  if (!bridgeHost.includes(securityMarker)) fail(`bridge host security contract marker missing: ${securityMarker}`);
}

const icon = read(iconPath);
if (!icon.includes('<svg ') || !icon.includes('<title ') || !icon.includes('<desc ')) fail('icon.svg must be an accessible SVG');
if (/<script\b|<foreignObject\b|\bhref=["']https?:\/\//i.test(icon)) fail('icon.svg contains forbidden active/external content');

console.log(JSON.stringify({
  schema: 'swir.web-sdk-template-check/1.0',
  valid: true,
  packageId: manifest.packageId,
  appId: manifest.id,
  sdkVersion,
  platformApi: compatibility.platformApi,
  permissions: manifest.permissions
}));
