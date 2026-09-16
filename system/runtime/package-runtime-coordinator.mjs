import { EventEmitter } from 'node:events';
import { resolveSystemPackageProvider } from '../providers/package-provider-registry.mjs';
import { SystemPackageLaunchBroker } from './package-launch-broker.mjs';

function assertProviderPlan(plan) {
  if (!plan || typeof plan !== 'object' || Array.isArray(plan)) throw new Error('provider plan must be an object');
  if (plan.schema !== 'swir.package-provider-plan/0.1') throw new Error('unsupported provider plan schema');
  if (plan.mode !== 'preview' || plan.readOnly !== true || plan.autoExecutable !== false) throw new Error('provider plan must remain read-only and non-executable');
  if (plan.privilegedMutationRequiresPlan !== true || plan.privilegedMutationRequiresJournal !== true) throw new Error('provider plan must require privileged transaction plan and journal');
  if (plan.signatureVerificationRequired !== true) throw new Error('provider plan must require signature verification');
  if (plan.status !== 'ready' || plan.capabilityAvailable !== true) throw new Error(`provider capability unavailable: ${plan.requiredCapability || 'unknown'}`);
}

export class SystemPackageRuntimeCoordinator extends EventEmitter {
  #broker;
  #providerResolver;

  constructor({ broker = new SystemPackageLaunchBroker(), providerResolver = resolveSystemPackageProvider } = {}) {
    super();
    if (!broker || typeof broker.launch !== 'function') throw new Error('package launch broker is required');
    if (typeof providerResolver !== 'function') throw new Error('provider resolver must be a function');
    this.#broker = broker;
    this.#providerResolver = providerResolver;
    for (const event of ['started', 'exited', 'processError']) {
      if (typeof this.#broker.on === 'function') this.#broker.on(event, record => this.emit(event, record));
    }
  }

  plan(manifest, { host = {} } = {}) {
    const plan = this.#providerResolver(manifest, host);
    if (!plan || plan.schema !== 'swir.package-provider-plan/0.1') throw new Error('provider resolver returned an invalid plan');
    return plan;
  }

  launch(manifest, verification, options = {}) {
    const { host = {}, ...runtimeOptions } = options || {};
    const providerPlan = this.#providerResolver(manifest, host);
    assertProviderPlan(providerPlan);
    const launchReceipt = this.#broker.launch(manifest, verification, runtimeOptions);
    if (launchReceipt.provider !== providerPlan.provider || launchReceipt.executionClass !== providerPlan.executionClass) {
      throw new Error('launch receipt diverged from approved provider plan');
    }
    return Object.freeze({
      schema: 'swir.system-package-runtime-coordinator/0.1',
      packageId: manifest.id,
      provider: providerPlan.provider,
      executionClass: providerPlan.executionClass,
      providerPlan,
      launchReceipt
    });
  }

  get(appId) { return this.#broker.get(appId); }
  list(options) { return this.#broker.list(options); }
  stop(appId, options) { return this.#broker.stop(appId, options); }
  forget(appId) { return this.#broker.forget(appId); }
}

export const SystemPackageRuntimeCoordinatorPolicy = Object.freeze({
  schema: 'swir.system-package-runtime-coordinator/0.1',
  providerPlanSchema: 'swir.package-provider-plan/0.1',
  verificationSchema: 'swir.package-verification/0.1',
  launchBrokerSchema: 'swir.system-package-launch/0.1',
  providerMustBeReady: true,
  providerPlanReadOnly: true,
  providerPlanAutoExecutable: false,
  signatureVerificationRequired: true,
  privilegedMutationRequiresPlan: true,
  privilegedMutationRequiresJournal: true,
  routingByExecutionClass: true,
  windowsKernelDriversAsLinuxDrivers: false
});
