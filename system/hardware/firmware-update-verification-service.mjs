import { FwupdLvfsService, assertSafeFwupdLvfsInventory } from './fwupd-lvfs-service.mjs';
import { FileFirmwareUpdateJournal } from './firmware-update-transaction-service.mjs';

const RESULT_SCHEMA = 'swir.firmware-update-verification/0.1';
const SAFE_SOURCE_STATES = new Set(['committed', 'staged-reboot-required', 'verified']);
const TRANSACTION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$/;

function fail(code, message) {
  const error = new Error(message);
  error.name = 'FirmwareUpdateVerificationError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function clean(value, max = 512) {
  return String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, max);
}

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function assessmentFor(entry, device, checkedAt) {
  const targetVersion = clean(entry?.plan?.binding?.targetVersion, 128) || null;
  const currentVersion = clean(device?.version, 128) || null;
  const updateError = clean(device?.updateError, 1024) || null;
  const devicePresent = Boolean(device);
  const versionMatches = devicePresent && targetVersion !== null && currentVersion === targetVersion;
  const verified = versionMatches && updateError === null;

  let status;
  if (verified) status = 'verified';
  else if (!devicePresent) status = 'device-not-present';
  else if (entry.state === 'staged-reboot-required' && updateError === null) status = 'pending-reboot-or-power-cycle';
  else status = 'needs-review';

  return Object.freeze({
    schema: RESULT_SCHEMA,
    transactionId: entry.transactionId,
    checkedAt,
    status,
    verified,
    devicePresent,
    deviceId: entry?.plan?.binding?.deviceId ?? null,
    fromVersion: entry?.plan?.binding?.currentVersion ?? null,
    targetVersion,
    currentVersion,
    updateState: Number.isInteger(device?.updateState) ? device.updateState : null,
    updateError,
    planDigest: entry.planDigest,
    sourceTransactionState: entry.state,
    automaticRollback: false,
    rebootOrPowerCycleProven: false,
    physicalHardwareQualification: false,
    operatorReviewRequired: !verified
  });
}

export class FirmwareUpdateVerificationService {
  #inventory;
  #journal;
  #clock;

  constructor({
    inventoryService = new FwupdLvfsService(),
    journal = new FileFirmwareUpdateJournal(),
    clock = () => new Date().toISOString()
  } = {}) {
    assert(typeof inventoryService?.inventory === 'function', 'FIRMWARE_VERIFY_INVENTORY_REQUIRED', 'fwupd/LVFS inventory service is required');
    assert(typeof journal?.read === 'function' && typeof journal?.write === 'function', 'FIRMWARE_VERIFY_JOURNAL_REQUIRED', 'firmware transaction journal is required');
    assert(typeof clock === 'function', 'FIRMWARE_VERIFY_CLOCK_REQUIRED', 'verification clock is required');
    this.#inventory = inventoryService;
    this.#journal = journal;
    this.#clock = clock;
  }

  async verify(transactionId) {
    assert(typeof transactionId === 'string' && TRANSACTION_ID.test(transactionId), 'FIRMWARE_VERIFY_TRANSACTION_ID_INVALID', 'firmware transaction id is invalid');
    const entry = this.#journal.read(transactionId);
    assert(SAFE_SOURCE_STATES.has(entry.state), 'FIRMWARE_VERIFICATION_STATE_UNSAFE', 'only successful or already verified firmware transactions may be verified');
    assert(entry?.plan?.binding?.deviceId, 'FIRMWARE_VERIFY_DEVICE_ID_MISSING', 'firmware journal is missing the bound device id');

    const inventory = await this.#inventory.inventory();
    assertSafeFwupdLvfsInventory(inventory);
    assert(inventory.available === true, 'FIRMWARE_VERIFY_PROVIDER_UNAVAILABLE', 'fwupd/LVFS is unavailable during verification');
    assert(inventory.probe?.trustedBinary === true, 'FIRMWARE_VERIFY_BINARY_UNTRUSTED', 'fwupd verification inventory did not come from a trusted binary');

    const matches = (Array.isArray(inventory.devices) ? inventory.devices : [])
      .filter(device => device?.deviceId === entry.plan.binding.deviceId);
    assert(matches.length <= 1, 'FIRMWARE_VERIFY_DEVICE_AMBIGUOUS', 'firmware verification found duplicate device identities');

    const checkedAt = this.#clock();
    const result = assessmentFor(entry, matches[0] ?? null, checkedAt);
    const updated = {
      ...clone(entry),
      state: result.verified ? 'verified' : entry.state,
      updatedAt: checkedAt,
      verification: clone(result),
      recovery: {
        ...clone(entry.recovery),
        automaticRollback: false,
        operatorReviewRequired: !result.verified,
        note: result.verified
          ? 'Installed firmware version matches the reviewed target. This is transaction verification only and does not prove physical-hardware qualification or a required reboot/power-cycle.'
          : 'Firmware state is not yet verified. Do not retry, downgrade or force a flash automatically; follow device-specific operator review and recovery guidance.'
      }
    };
    this.#journal.write(updated);
    return result;
  }
}

export const FirmwareUpdateVerificationPolicy = Object.freeze({
  schema: 'swir.firmware-update-verification-policy/0.1',
  readOnlyHardwareInspection: true,
  exactJournalBindingRequired: true,
  trustedFwupdInventoryRequired: true,
  exactDeviceIdentityRequired: true,
  targetVersionMatchRequired: true,
  updateErrorMustBeClear: true,
  failedTransactionAutoPromotion: false,
  automaticRetry: false,
  automaticRollback: false,
  rebootOrPowerCycleProvenBySoftware: false,
  physicalHardwareQualification: false
});
