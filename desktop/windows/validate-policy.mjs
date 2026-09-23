import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..');
const catalogSource = fs.readFileSync(path.join(repoRoot, 'swir-packages.js'), 'utf8');
const policy = JSON.parse(fs.readFileSync(path.join(here, 'app-policy.json'), 'utf8'));
const knownPermissions = new Set([
  'storage',
  'files.read',
  'files.write',
  'clipboard',
  'network',
  'identity.basic',
  'notifications',
  'downloads'
]);

const sandbox = { window: {}, Object };
vm.createContext(sandbox);
vm.runInContext(catalogSource, sandbox, { filename: 'swir-packages.js', timeout: 1000 });

const catalog = Array.isArray(sandbox.window.SWIR_PACKAGE_CATALOG) ? sandbox.window.SWIR_PACKAGE_CATALOG : [];
const catalogErrors = [];
const desktopPackages = catalog.filter(pkg => {
  const editions = pkg?.compatibility?.editions;
  if (!Array.isArray(editions) || editions.length < 1) {
    catalogErrors.push(`${pkg?.packageId || pkg?.id || '<missing>'}: compatibility.editions is required for Desktop policy scoping`);
    return false;
  }
  return editions.map(value => String(value).trim().toUpperCase()).includes('DESKTOP');
});
const expected = new Map(desktopPackages.map(pkg => [pkg.packageId, {
  packageId: pkg.packageId,
  entry: pkg.entry,
  permissions: [...(pkg.permissions || [])].sort()
}]));
const actual = new Map((policy.packages || []).map(pkg => [pkg.packageId, {
  packageId: pkg.packageId,
  entry: pkg.entry,
  permissions: [...(pkg.permissions || [])].sort()
}]));

const errors = [...catalogErrors];
if (policy.schema !== 'swir.desktop-policy/0.1') errors.push(`Unsupported policy schema: ${policy.schema}`);
for (const [packageId, exp] of expected) {
  const got = actual.get(packageId);
  if (!got) { errors.push(`Missing desktop policy for ${packageId}`); continue; }
  if (got.entry !== exp.entry) errors.push(`${packageId}: entry mismatch (${got.entry} != ${exp.entry})`);
  if (JSON.stringify(got.permissions) !== JSON.stringify(exp.permissions)) errors.push(`${packageId}: permission set mismatch`);
  for (const permission of got.permissions) {
    if (!knownPermissions.has(permission)) errors.push(`${packageId}: unknown Desktop permission ${permission}`);
  }
}
for (const packageId of actual.keys()) {
  if (!expected.has(packageId)) errors.push(`Desktop policy has package not present in the Desktop-compatible SWIR catalog: ${packageId}`);
}
if (new Set((policy.packages || []).map(pkg => pkg.packageId)).size !== (policy.packages || []).length) errors.push('Duplicate packageId in app-policy.json');

if (errors.length) {
  console.error('Desktop policy validation failed:');
  for (const error of errors) console.error(` - ${error}`);
  process.exit(1);
}
console.log(`Desktop policy OK: ${actual.size} package policies match Desktop-compatible swir-packages.js entries; permission allowlist is fail-closed`);
