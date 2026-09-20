import { assertSafeDriverPlan } from './driver-resolver.mjs';
import { assertVendorRepositoryTransactionBinding } from './vendor-repository-transaction-binding.mjs';
import {
  assertVendorRepositoryActivationPlan,
  buildVendorRepositoryActivationPlan
} from './vendor-repository-activation-transaction-service.mjs';

const SCHEMA = 'swir.driver-center-vendor-repository-review/0.1';
const VENDOR_CLASS = 'vendor-official-repository';
const HEX64 = /^[a-f0-9]{64}$/;

function fail(code, message) {
  const error = new Error(message);
  error.name = 'DriverCenterVendorRepositoryError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function strings(value) {
  return Array.isArray(value) ? value.filter(item => typeof item === 'string' && item.trim()).map(item => item.trim()) : [];
}

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function matchingVendorSource(operation) {
  const sources = (operation?.sources || []).filter(source => source?.class === VENDOR_CLASS);
  assert(sources.length === 1, 'VENDOR_SOURCE_CARDINALITY_INVALID', 'Driver Center operation must resolve to exactly one verified vendor source before activation.');
  const source = sources[0];
  assert(typeof source.repositoryId === 'string' && source.repositoryId.length > 0, 'VENDOR_REPOSITORY_ID_REQUIRED', 'Verified vendor source requires repositoryId.');
  assert(source?.verification?.schema === 'swir.vendor-repository-transaction-binding/0.1', 'VENDOR_BINDING_MARKER_INVALID', 'Verified vendor source is missing transaction-binding metadata.');
  assert(HEX64.test(String(source?.verification?.bindingDigest || '')), 'VENDOR_BINDING_DIGEST_INVALID', 'Verified vendor source binding digest is invalid.');
  assert(Array.isArray(source?.verification?.packages) && source.verification.packages.length > 0, 'VENDOR_PACKAGE_SCOPE_MISSING', 'Verified vendor source must retain package scope.');
  return source;
}

function findBinding(bindings, source, now) {
  const matches = [];
  for (const candidate of bindings || []) {
    try {
      assertVendorRepositoryTransactionBinding(candidate);
    } catch {
      continue;
    }
    if (candidate.bindingDigest !== source.verification.bindingDigest) continue;
    if (candidate.bound?.repository?.id !== source.repositoryId) continue;
    const expiry = Date.parse(candidate.bound?.metadata?.effectiveValidUntil);
    if (!Number.isFinite(expiry) || expiry < now.getTime()) continue;
    matches.push(candidate);
  }
  assert(matches.length === 1, 'VENDOR_BINDING_NOT_UNIQUE', 'Driver Center requires exactly one fresh binding matching the verified vendor source.');
  return matches[0];
}

function assertPackageScope(operation, binding, source) {
  const requested = new Set(strings(operation?.packageCandidates));
  const verified = new Set(strings(source?.verification?.packages));
  const bound = new Set(strings(binding?.bound?.packages));
  const common = [...requested].filter(name => verified.has(name) && bound.has(name)).sort();
  assert(common.length > 0, 'VENDOR_PACKAGE_SCOPE_MISMATCH', 'Driver Center operation has no package inside the verified vendor binding scope.');
  assert(common.length === bound.size, 'VENDOR_PACKAGE_SCOPE_WIDENED', 'Vendor binding package scope must be fully represented by the selected Driver Center operation.');
  return common;
}

export function createVendorRepositoryActivationReview({
  driverPlan,
  operationId,
  vendorRepositoryBindings,
  sourceRoot,
  now = new Date()
} = {}) {
  assertSafeDriverPlan(driverPlan);
  const current = now instanceof Date ? new Date(now.getTime()) : new Date(now);
  assert(Number.isFinite(current.getTime()), 'VENDOR_REVIEW_CLOCK_INVALID', 'Driver Center vendor activation review requires a valid clock.');
  assert(Array.isArray(vendorRepositoryBindings), 'VENDOR_BINDINGS_INVALID', 'Vendor repository bindings must be an array.');
  assert(typeof operationId === 'string' && operationId.length > 0, 'VENDOR_OPERATION_ID_REQUIRED', 'Driver Center operation id is required.');

  const operations = (driverPlan.operations || []).filter(operation => operation?.id === operationId);
  assert(operations.length === 1, 'VENDOR_OPERATION_NOT_UNIQUE', 'Driver Center operation id must resolve to exactly one operation.');
  const operation = operations[0];
  assert(operation.kind === 'review-package', 'VENDOR_OPERATION_KIND_INVALID', 'Vendor repository activation is only valid for a package review operation.');
  assert(operation.requiresPrivilege === true, 'VENDOR_OPERATION_PRIVILEGE_INVALID', 'Vendor repository activation review must retain privileged-operation semantics.');
  assert(operation.rollback !== 'not-required', 'VENDOR_OPERATION_RECOVERY_INVALID', 'Vendor repository activation requires recovery metadata.');

  const source = matchingVendorSource(operation);
  const binding = findBinding(vendorRepositoryBindings, source, current);
  const packages = assertPackageScope(operation, binding, source);
  const activationPlan = buildVendorRepositoryActivationPlan(binding, { sourceRoot, now: current });
  assertVendorRepositoryActivationPlan(activationPlan, { allowedSourceRoot: sourceRoot, now: current });
  assert(activationPlan.bindingDigest === source.verification.bindingDigest, 'VENDOR_ACTIVATION_BINDING_MISMATCH', 'Activation plan no longer matches Driver Center verified source binding.');
  assert(activationPlan.repositoryId === source.repositoryId, 'VENDOR_ACTIVATION_REPOSITORY_MISMATCH', 'Activation plan repository no longer matches Driver Center verified source.');

  return Object.freeze({
    schema: SCHEMA,
    mode: 'review',
    readOnly: true,
    autoExecutable: false,
    mutationAuthorized: false,
    repositoryEnablementAuthorized: false,
    requiresExplicitConfirmation: true,
    requiresPrivilege: true,
    operation: Object.freeze({
      id: operation.id,
      deviceKey: operation.deviceKey,
      kind: operation.kind,
      packageManager: operation.packageManager || null,
      packages: Object.freeze(packages)
    }),
    vendor: Object.freeze({
      repositoryId: source.repositoryId,
      bindingDigest: binding.bindingDigest,
      evidenceValidUntil: binding.bound.metadata.effectiveValidUntil,
      sourceRef: source.ref
    }),
    activationPlan: clone(activationPlan),
    packageMutationDeferred: true,
    directAptMutationAllowed: false,
    directPkexecAllowed: false
  });
}

export function assertVendorRepositoryActivationReview(review, { sourceRoot, now = new Date() } = {}) {
  assert(review?.schema === SCHEMA, 'VENDOR_REVIEW_SCHEMA_INVALID', 'Driver Center vendor repository review schema mismatch.');
  assert(review.mode === 'review' && review.readOnly === true && review.autoExecutable === false, 'VENDOR_REVIEW_MODE_INVALID', 'Driver Center vendor repository review must remain non-executable.');
  assert(review.mutationAuthorized === false && review.repositoryEnablementAuthorized === false, 'VENDOR_REVIEW_PREAUTHORIZED', 'Driver Center review cannot pre-authorize repository mutation.');
  assert(review.requiresExplicitConfirmation === true && review.requiresPrivilege === true, 'VENDOR_REVIEW_AUTH_BOUNDARY_INVALID', 'Driver Center review must require explicit privileged confirmation.');
  assert(review.operation?.kind === 'review-package' && Array.isArray(review.operation?.packages) && review.operation.packages.length > 0, 'VENDOR_REVIEW_OPERATION_INVALID', 'Driver Center review operation is invalid.');
  assert(typeof review.vendor?.repositoryId === 'string' && HEX64.test(String(review.vendor?.bindingDigest || '')), 'VENDOR_REVIEW_BINDING_INVALID', 'Driver Center review binding identity is invalid.');
  assert(review.activationPlan?.bindingDigest === review.vendor.bindingDigest && review.activationPlan?.repositoryId === review.vendor.repositoryId, 'VENDOR_REVIEW_ACTIVATION_SCOPE_MISMATCH', 'Activation plan is not bound to the reviewed vendor source.');
  assertVendorRepositoryActivationPlan(review.activationPlan, { allowedSourceRoot: sourceRoot, now });
  assert(review.packageMutationDeferred === true && review.directAptMutationAllowed === false && review.directPkexecAllowed === false, 'VENDOR_REVIEW_MUTATION_BOUNDARY_INVALID', 'Driver Center vendor review crossed the mutation boundary.');
  return true;
}

export class DriverCenterVendorRepositoryCoordinator {
  constructor({ activationService } = {}) {
    assert(typeof activationService?.execute === 'function', 'VENDOR_ACTIVATION_SERVICE_REQUIRED', 'Vendor repository activation transaction service is required.');
    assert(typeof activationService?.recoverSource === 'function', 'VENDOR_RECOVERY_SERVICE_REQUIRED', 'Vendor repository recovery service is required.');
    this.activationService = activationService;
  }

  async activate(review, context = {}) {
    assertVendorRepositoryActivationReview(review, { sourceRoot: context.sourceRoot, now: context.now || new Date() });
    assert(context.confirmationDigest === review.activationPlan.activationDigest, 'VENDOR_CONFIRMATION_MISMATCH', 'Driver Center activation requires the exact visible activation digest.');
    return this.activationService.execute(review.activationPlan, context);
  }

  async recover(transactionId, review, context = {}) {
    assertVendorRepositoryActivationReview(review, { sourceRoot: context.sourceRoot, now: context.now || new Date() });
    assert(context.confirmationDigest === review.activationPlan.activationDigest, 'VENDOR_CONFIRMATION_MISMATCH', 'Driver Center recovery requires the exact visible activation digest.');
    return this.activationService.recoverSource(transactionId, context);
  }

  async deactivate(transactionId, review, context = {}) {
    assertVendorRepositoryActivationReview(review, { sourceRoot: context.sourceRoot, now: context.now || new Date() });
    assert(context.confirmationDigest === review.activationPlan.activationDigest, 'VENDOR_CONFIRMATION_MISMATCH', 'Driver Center deactivation requires the exact visible activation digest.');
    assert(typeof this.activationService?.journal?.read === 'function' && typeof this.activationService?.journal?.write === 'function', 'VENDOR_DEACTIVATION_JOURNAL_REQUIRED', 'Deactivation requires the activation transaction journal.');
    assert(typeof this.activationService?.sourceStore?.inspect === 'function' && typeof this.activationService?.sourceStore?.restore === 'function', 'VENDOR_DEACTIVATION_SOURCE_STORE_REQUIRED', 'Deactivation requires the guarded activation source store.');
    assert(typeof this.activationService?.authorizationBroker?.authorize === 'function', 'VENDOR_DEACTIVATION_AUTHORIZATION_REQUIRED', 'Deactivation requires the existing privilege broker.');
    if (this.activationService.enforceRoot && typeof process.geteuid === 'function') {
      assert(process.geteuid() === 0, 'VENDOR_DEACTIVATION_ROOT_REQUIRED', 'Vendor repository deactivation must execute inside the existing privileged broker.');
    }

    const record = this.activationService.journal.read(transactionId);
    assert(record?.state === 'committed', 'VENDOR_DEACTIVATION_STATE_INVALID', 'Only a committed activation transaction can be explicitly deactivated.');
    assert(record?.plan?.activationDigest === review.activationPlan.activationDigest, 'VENDOR_DEACTIVATION_PLAN_MISMATCH', 'Committed transaction does not match the reviewed activation digest.');
    assert(record?.plan?.bindingDigest === review.vendor.bindingDigest, 'VENDOR_DEACTIVATION_BINDING_MISMATCH', 'Committed transaction does not match the reviewed binding digest.');
    const current = this.activationService.sourceStore.inspect(record.plan.source.path);
    assert(current?.existed === true && current.sha256 === record.plan.source.sha256, 'VENDOR_DEACTIVATION_SOURCE_DIVERGED', 'APT source changed after activation; refusing automatic deactivation.');

    const authorization = await this.activationService.authorizationBroker.authorize({
      schema: 'swir.vendor-repository-deactivation-authorization-request/0.1',
      repositoryId: record.plan.repositoryId,
      activationDigest: record.plan.activationDigest,
      bindingDigest: record.plan.bindingDigest,
      transactionId
    }, context);
    assert(authorization?.authorized === true && typeof authorization.authorizationId === 'string' && authorization.authorizationId.length > 0, 'VENDOR_DEACTIVATION_NOT_AUTHORIZED', 'Existing privilege broker did not authorize repository deactivation.');

    this.activationService.sourceStore.restore(record.plan.source.path, record.previousSource);
    const restored = this.activationService.sourceStore.inspect(record.plan.source.path);
    const previousDigest = record.previousSource?.sha256 ?? null;
    assert(restored.existed === record.previousSource?.existed && restored.sha256 === previousDigest, 'VENDOR_DEACTIVATION_POST_VERIFY_FAILED', 'Vendor repository source did not return to its exact pre-activation state.');
    const updated = {
      ...record,
      state: 'rolled-back',
      updatedAt: typeof this.activationService.clock === 'function' ? this.activationService.clock() : new Date().toISOString(),
      deactivationAuthorizationId: authorization.authorizationId,
      result: { ...(record.result || {}), explicitDeactivation: true, restoredPreviousSource: true },
      recovery: { operatorReviewRequired: false, sourceRestoreRequired: false, automaticPackageMutation: false }
    };
    this.activationService.journal.write(updated);
    return clone(updated);
  }
}

export const DriverCenterVendorRepositoryPolicy = Object.freeze({
  schema: 'swir.driver-center-vendor-repository-policy/0.1',
  exactDriverOperationRequired: true,
  exactFreshBindingRequired: true,
  packageScopeIntersectionRequired: true,
  exactActivationDigestConfirmationRequired: true,
  existingJournaledActivationServiceRequired: true,
  directAptMutationAllowed: false,
  directPkexecAllowed: false,
  automaticEnablement: false,
  packageInstallIsSeparateTransaction: true
});
