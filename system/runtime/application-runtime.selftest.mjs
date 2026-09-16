import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { SystemApplicationRuntime, SystemApplicationRuntimePolicy } from './application-runtime.mjs';

class FakeRuntime extends EventEmitter {
  constructor(kind) { super(); this.kind = kind; this.records = new Map(); }
  launch(manifest) {
    const record = { appId: manifest.id, pid: this.kind === 'linux' ? 101 : 202, state: 'running', startedAt: '2026-09-16T00:00:00.000Z' };
    this.records.set(manifest.id, record);
    this.emit('started', record);
    return { ...record };
  }
  list({ includeExited = true } = {}) { return [...this.records.values()].filter(r => includeExited || r.state === 'running').map(r => ({ ...r })); }
  get(id) { const r = this.records.get(id); return r ? { ...r } : null; }
  stop(id) { const r = this.records.get(id); if (!r || r.state !== 'running') return false; r.state = 'exited'; r.exitCode = 0; this.emit('exited', { ...r }); return true; }
  forget(id) { const r = this.records.get(id); if (!r || r.state === 'running') throw new Error('cannot forget a running application'); return this.records.delete(id); }
}

const linux = new FakeRuntime('linux');
const windows = new FakeRuntime('windows');
const runtime = new SystemApplicationRuntime({ nativeService: linux, windowsSupervisor: windows });
const events = [];
runtime.on('started', event => events.push(event));

const base = { schema: 'swir.package-provider/0.2', targetEditions: ['system'] };
const nativeManifest = { ...base, id: 'swir.test.native', executionClass: 'linux-native' };
const windowsManifest = { ...base, id: 'swir.test.windows', executionClass: 'windows-compat' };

assert.equal(runtime.launch(nativeManifest).executionClass, 'linux-native');
assert.equal(runtime.launch(windowsManifest).executionClass, 'windows-compat');
assert.equal(runtime.get('swir.test.native').pid, 101);
assert.equal(runtime.get('swir.test.windows').pid, 202);
assert.equal(runtime.list().length, 2);
assert.deepEqual(events.map(e => e.executionClass), ['linux-native', 'windows-compat']);
assert.throws(() => runtime.launch(nativeManifest), /already tracked/);
assert.throws(() => runtime.launch({ ...base, id: 'bad.web', executionClass: 'swir-web' }), /unsupported System Edition execution class/);
assert.throws(() => runtime.launch({ ...nativeManifest, id: 'bad.desktop', targetEditions: ['desktop'] }), /does not target System Edition/);
assert.equal(runtime.stop('swir.test.native'), true);
assert.equal(runtime.forget('swir.test.native'), true);
assert.equal(runtime.get('swir.test.native'), null);
assert.equal(SystemApplicationRuntimePolicy.windowsKernelDriversAsLinuxDrivers, false);
assert.deepEqual(SystemApplicationRuntimePolicy.executionClasses, ['linux-native', 'windows-compat']);
console.log('System Application Runtime self-tests passed');
