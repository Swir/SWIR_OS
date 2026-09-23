#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = rel => fs.readFileSync(path.join(root, rel), 'utf8');

const packageSandbox = { window: {} };
vm.runInNewContext(read('swir-packages.js'), packageSandbox, { filename: 'swir-packages.js' });
const catalog = packageSandbox.window.SWIR_PACKAGE_CATALOG;
assert.ok(Array.isArray(catalog), 'package catalog must be an array');

const widgets = catalog.filter(pkg => pkg.category === 'Widgets');
assert.equal(widgets.length, 2, 'expected two official Web widget packages');
assert.deepEqual([...widgets.map(pkg => pkg.id)].sort(), ['widget-clock', 'widget-system']);

for (const pkg of widgets) {
  assert.equal(pkg.schema, 'swir.app/1.0');
  assert.equal(pkg.type, 'iframe');
  assert.equal(pkg.desktop, false, `${pkg.id} must not create a desktop app icon`);
  assert.deepEqual(Array.from(pkg.compatibility?.editions || []), ['WEB'], `${pkg.id} must stay Web-scoped until native widget support exists`);
  assert.deepEqual(Array.from(pkg.permissions || []), [], `${pkg.id} must remain permission-free/read-only`);
  assert.deepEqual(Array.from(pkg.associations || []), [], `${pkg.id} must not register file handlers`);
  assert.match(pkg.packageId, /^swir\.widget\.[a-z0-9.-]+$/);
  assert.match(pkg.entry, /^\.\/swir-widget-[a-z0-9-]+\.html$/);
  assert.ok(fs.existsSync(path.join(root, pkg.entry.slice(2))), `missing widget entry ${pkg.entry}`);
}

const hostSource = read('swir-widgets.js');
const hostSandbox = { console, setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask };
vm.runInNewContext(hostSource, hostSandbox, { filename: 'swir-widgets.js' });
const api = hostSandbox.SwirWidgets;
assert.ok(api, 'SwirWidgets API must be exported');
assert.equal(api.meta.model, 'verified-installable-packages');
assert.ok(api.descriptorFor(widgets.find(pkg => pkg.id === 'widget-clock')));
assert.ok(api.descriptorFor(widgets.find(pkg => pkg.id === 'widget-system')));

const verifiedClock = {
  id: 'widget-clock', installed: true, kind: 'swir-app-package',
  verification: { officialCatalog: true }
};
const forgedSystem = {
  id: 'widget-system', installed: true, kind: 'swir-app-package',
  verification: { officialCatalog: false }
};
const legacyClock = { id: 'widget-clock', installed: true, source: 'legacy-store' };
const resolved = api.resolveInstalledWidgets([verifiedClock, forgedSystem, legacyClock], catalog);
assert.equal(resolved.length, 1, 'widget host must fail closed for unverified/legacy package records');
assert.equal(resolved[0].package.id, 'widget-clock');

const forgedCatalog = catalog.map(pkg => pkg.id === 'widget-clock' ? { ...pkg, entry: './evil.html' } : pkg);
assert.equal(api.resolveInstalledWidgets([verifiedClock], forgedCatalog).length, 0, 'widget renderer must reject an altered official entry');

for (const pkg of widgets) {
  const html = read(pkg.entry.slice(2));
  assert.doesNotMatch(html, /\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|https?:\/\//i, `${pkg.id} must not contain a network path`);
  assert.match(html, /Read-only/i, `${pkg.id} must disclose its read-only boundary`);
}

const v17 = read('swir-v17.js');
assert.match(v17, /load\('\.\/swir-widgets\.js'\)/, 'shell integration must load the widget host');
assert.match(v17, /SwirWidgets\.render\(\)/, 'shell integration must render verified installed widgets');

const installPipeline = read('swir-install-pipeline.js');
for (const protectedField of ['category', 'type', 'entry']) {
  assert.match(installPipeline, new RegExp(`['\"]${protectedField}['\"]`), `catalog trust matching must protect ${protectedField}`);
}
assert.match(installPipeline, /officialCatalog/, 'package verification record must preserve official catalog trust state');

const spec = read('SWIR-APP-PACKAGE-1.0.md');
assert.match(spec, /Installable Web widgets/i, 'package specification must document widget packages');
assert.match(spec, /swir\.widget\.clock/);
assert.match(spec, /swir\.widget\.system/);

console.log('SWIR installable Web widget package verification passed.');
