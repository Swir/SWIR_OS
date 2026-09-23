import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const catalogFile = path.join(root, 'swir-packages.js');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(catalogFile, 'utf8'), sandbox, { filename: catalogFile });
const catalog = sandbox.window.SWIR_PACKAGE_CATALOG;
if (!Array.isArray(catalog) || !catalog.length) throw new Error('SWIR package catalog is empty or invalid.');

const failures = [];
const desktopPackages = catalog.filter(pkg => {
  const editions = pkg?.compatibility?.editions;
  if (!Array.isArray(editions) || editions.length < 1) {
    failures.push(`${pkg?.packageId || pkg?.id || '<missing>'}: compatibility.editions is required for Desktop isolation scoping`);
    return false;
  }
  return editions.map(value => String(value).trim().toUpperCase()).includes('DESKTOP');
});
if (!desktopPackages.length) failures.push('No Desktop-compatible packages found for App Bridge isolation validation');

const ready = [];
for (const pkg of desktopPackages) {
  const entry = String(pkg.entry || '').replace(/^\.\//, '');
  const file = path.join(root, entry);
  if (!entry || !fs.existsSync(file)) {
    failures.push(`${pkg.packageId}: missing entry ${entry || '(empty)'}`);
    continue;
  }
  const source = fs.readFileSync(file, 'utf8');
  if (/parent\.(?:Swir|SWIR_)/.test(source)) failures.push(`${pkg.packageId}: direct parent.Swir*/parent.SWIR_* access remains`);
  if (!source.includes('swir-app-bridge.js')) failures.push(`${pkg.packageId}: swir-app-bridge.js is not loaded`);
  if (!source.includes(`data-swir-package="${pkg.packageId}"`)) failures.push(`${pkg.packageId}: bridge package identity is missing/mismatched`);
  if (!source.includes(`data-swir-app="${pkg.id}"`)) failures.push(`${pkg.packageId}: bridge app identity is missing/mismatched`);
  if ((pkg.permissions || []).includes('network') && /\bfetch\s*\(/.test(source)) failures.push(`${pkg.packageId}: direct fetch() remains; use SwirAppBridge.network`);
  if ((pkg.permissions || []).includes('network') && !source.includes('bridge.network')) failures.push(`${pkg.packageId}: network package does not use App Bridge network transport`);
  if (!failures.some(x => x.startsWith(`${pkg.packageId}:`))) ready.push(pkg.packageId);
}

if (failures.length) {
  console.error('\nApp isolation readiness validation failed:');
  for (const failure of failures) console.error(` - ${failure}`);
  process.exit(1);
}
if (ready.length !== desktopPackages.length) {
  console.error(`Expected ${desktopPackages.length} Desktop bridge-ready packages but found ${ready.length}.`);
  process.exit(1);
}
console.log(`Desktop App isolation bridge-ready packages (${ready.length}/${desktopPackages.length}): ${ready.join(', ')}`);
