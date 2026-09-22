import fs from 'node:fs';
import path from 'node:path';

const runtimePath = path.join(import.meta.dirname, 'DesktopUpdateBackgroundHostRuntime.cs');
const controllerPath = path.join(import.meta.dirname, 'DesktopUpdateBackgroundHostController.cs');
const preparationHostPath = path.join(import.meta.dirname, 'DesktopUpdatePreparationHostService.cs');
const runtime = fs.readFileSync(runtimePath, 'utf8');
const controller = fs.readFileSync(controllerPath, 'utf8');
const preparationHost = fs.readFileSync(preparationHostPath, 'utf8');

function requireText(source, needle, message) {
  if (!source.includes(needle)) throw new Error(message);
}

function rejectText(source, needle, message) {
  if (source.includes(needle)) throw new Error(message);
}

requireText(runtime, '[ModuleInitializer]', 'Desktop Host must register the production background-update runtime at module initialization.');
requireText(runtime, 'Application.Idle += StartOnFirstIdle', 'Background runtime must start from the real WinForms host lifetime.');
requireText(runtime, 'Application.ApplicationExit += StopOnApplicationExit', 'Background runtime must drain on real Desktop Host shutdown.');
requireText(runtime, 'new DesktopUpdatePreparationHostService()', 'Production background runtime must reuse the signed update preparation host.');
requireText(runtime, 'preparationHost.RunBackgroundCycleAsync(', 'Runtime scheduler must execute the policy-aware signed background cycle.');
requireText(runtime, 'preparationHost.DescribeUserPolicy', 'Runtime scheduler must read the persisted Desktop update policy.');
requireText(runtime, 'preparationHost.SetUserPolicy', 'Runtime controller must retain authoritative policy mutation wiring.');
requireText(runtime, 'runtimeEligibility: () => IsRuntimeEligible(preparationHost)', 'Runtime scheduler must be independently gated by secure runtime eligibility.');
requireText(runtime, 'status.TryGetProperty("configured"', 'Runtime eligibility must require a fully configured preparation path.');
requireText(runtime, 'status.TryGetProperty("feedConfigured"', 'Runtime eligibility must require the signed release feed.');
requireText(runtime, 'status.TryGetProperty("failClosed"', 'Runtime eligibility must require the preparation host fail-closed contract.');
requireText(runtime, 'automaticRestart = false', 'Production background runtime must never advertise silent restart permission.');
requireText(runtime, 'runtime.DisposeAsync().AsTask().GetAwaiter().GetResult()', 'Desktop Host shutdown must synchronously drain the scheduler before process exit.');
requireText(runtime, 'Application.Idle -= StartOnFirstIdle', 'Runtime startup hook must be one-shot and removable during shutdown.');
requireText(runtime, 'Interlocked.Exchange(ref _startClaimed, 1)', 'Runtime startup must be idempotent.');
requireText(runtime, 'Interlocked.Exchange(ref _stopClaimed, 1)', 'Runtime shutdown must be idempotent.');

requireText(controller, 'failClosedRuntimeEligibility = true', 'Host controller must retain fail-closed runtime eligibility semantics.');
requireText(controller, 'await _scheduler.StopAsync()', 'Host controller must retain stale-scheduler shutdown paths.');
requireText(controller, 'automaticRestart = false', 'Host controller must continue to forbid automatic restart.');

requireText(preparationHost, 'RunBackgroundCycleAsync', 'Preparation host must retain the scheduler-safe background cycle.');
requireText(preparationHost, 'background-check-disabled-by-user-policy', 'Manual mode must suppress background network work.');
requireText(preparationHost, 'policy-changed-during-signed-check', 'Policy must be re-read after signed discovery.');
requireText(preparationHost, 'automaticRestart = false', 'Automatic preparation must not silently restart the Desktop Host.');

rejectText(runtime, 'Process.Start(', 'Background runtime must not bypass the guarded updater/restart pipeline.');
rejectText(runtime, 'HttpClient', 'Background lifetime binding must not create an alternate unsigned network path.');
rejectText(runtime, 'AutomaticRestart: true', 'Background runtime must never enable silent restart.');

console.log('Desktop background update runtime binding validated (host lifetime + policy + signed runtime eligibility + shutdown drain).');
