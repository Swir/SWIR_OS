import { EventEmitter } from 'node:events';
import { NativePackageExecutionService } from './native-package-execution-service.mjs';
import { WindowsCompatibilitySupervisor } from './windows-compat-supervisor.mjs';

function assertManifest(manifest) {
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) throw new Error('package manifest must be an object');
  if (manifest.schema !== 'swir.package-provider/0.2') throw new Error('unsupported package provider schema');
  if (!Array.isArray(manifest.targetEditions) || !manifest.targetEditions.includes('system')) throw new Error('package does not target System Edition');
  if (!['linux-native', 'windows-compat'].includes(manifest.executionClass)) throw new Error('unsupported System Edition execution class');
}

export class SystemApplicationRuntime extends EventEmitter {
  #native;
  #windows;
  #owners = new Map();

  constructor({ nativeService = new NativePackageExecutionService(), windowsSupervisor = new WindowsCompatibilitySupervisor() } = {}) {
    super();
    this.#native = nativeService;
    this.#windows = windowsSupervisor;
    this.#wire('linux-native', this.#native);
    this.#wire('windows-compat', this.#windows);
  }

  #wire(executionClass, runtime) {
    runtime.on('started', record => this.emit('started', { executionClass, ...record }));
    runtime.on('exited', record => this.emit('exited', { executionClass, ...record }));
    runtime.on('processError', record => this.emit('processError', { executionClass, ...record }));
  }

  launch(manifest, options = {}) {
    assertManifest(manifest);
    if (this.#owners.has(manifest.id)) throw new Error(`application already tracked: ${manifest.id}`);
    const executionClass = manifest.executionClass;
    const runtime = executionClass === 'linux-native' ? this.#native : this.#windows;
    const record = runtime.launch(manifest, options);
    this.#owners.set(manifest.id, executionClass);
    return { executionClass, ...record };
  }

  get(appId) {
    const executionClass = this.#owners.get(appId);
    if (!executionClass) return null;
    const runtime = executionClass === 'linux-native' ? this.#native : this.#windows;
    const record = runtime.get(appId);
    return record ? { executionClass, ...record } : null;
  }

  list({ includeExited = true } = {}) {
    const native = this.#native.list({ includeExited }).map(record => ({ executionClass: 'linux-native', ...record }));
    const windows = this.#windows.list({ includeExited }).map(record => ({ executionClass: 'windows-compat', ...record }));
    return [...native, ...windows].sort((a, b) => String(a.startedAt).localeCompare(String(b.startedAt)));
  }

  stop(appId, options) {
    const executionClass = this.#owners.get(appId);
    if (!executionClass) return false;
    return (executionClass === 'linux-native' ? this.#native : this.#windows).stop(appId, options);
  }

  forget(appId) {
    const executionClass = this.#owners.get(appId);
    if (!executionClass) return false;
    const runtime = executionClass === 'linux-native' ? this.#native : this.#windows;
    const forgotten = runtime.forget(appId);
    if (forgotten) this.#owners.delete(appId);
    return forgotten;
  }
}

export const SystemApplicationRuntimePolicy = Object.freeze({
  schema: 'swir.system-application-runtime/0.1',
  acceptedManifest: 'swir.package-provider/0.2',
  targetEdition: 'system',
  executionClasses: ['linux-native', 'windows-compat'],
  windowsCompatibility: ['swir.compat.wine', 'swir.compat.proton'],
  windowsKernelDriversAsLinuxDrivers: false,
  routingByExecutionClass: true
});
