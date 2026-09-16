import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { buildWindowsCompatibilityPlan } from './windows-compat-execution-service.mjs';

const SAFE_ENV = new Set(['HOME','LANG','LC_ALL','LC_CTYPE','PATH','TERM','USER','LOGNAME','DISPLAY','WAYLAND_DISPLAY','XDG_RUNTIME_DIR','XDG_CURRENT_DESKTOP','DBUS_SESSION_BUS_ADDRESS']);

function sanitizeEnvironment(source = process.env) {
  return Object.fromEntries(Object.entries(source).filter(([key, value]) => SAFE_ENV.has(key) && typeof value === 'string'));
}

function ensureDirectory(directory) {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const stat = fs.statSync(directory);
  if (!stat.isDirectory()) throw new Error('compatibility prefix is not a directory');
  return fs.realpathSync(directory);
}

function assertRuntime(runtime) {
  if (!runtime) throw new Error('Windows compatibility runtime is unavailable');
  const resolved = fs.realpathSync(runtime);
  const stat = fs.statSync(resolved);
  if (!stat.isFile()) throw new Error('compatibility runtime must be a regular file');
  if ((stat.mode & 0o111) === 0) throw new Error('compatibility runtime is not executable');
  return resolved;
}

function buildRuntimeArgs(plan) {
  if (plan.provider === 'swir.compat.wine') return [plan.entryPoint, ...plan.args];
  if (plan.provider === 'swir.compat.proton') return ['run', plan.entryPoint, ...plan.args];
  throw new Error('unsupported Windows compatibility provider');
}

export function launchWindowsCompatibilityApp(manifest, options = {}) {
  const plan = buildWindowsCompatibilityPlan(manifest, options);
  const runtime = assertRuntime(plan.runtime);
  const prefix = ensureDirectory(plan.prefix);
  const environment = sanitizeEnvironment(options.environment || process.env);

  if (plan.provider === 'swir.compat.wine') environment.WINEPREFIX = prefix;
  if (plan.provider === 'swir.compat.proton') environment.STEAM_COMPAT_DATA_PATH = prefix;

  const child = spawn(runtime, buildRuntimeArgs(plan), {
    cwd: options.cwd ? fs.realpathSync(options.cwd) : path.dirname(plan.entryPoint),
    env: environment,
    shell: false,
    windowsHide: true,
    stdio: options.stdio || 'ignore',
    detached: false
  });

  return {
    appId: plan.appId,
    pid: child.pid,
    child,
    runtime,
    provider: plan.provider,
    prefix,
    entryPoint: plan.entryPoint
  };
}

export const WindowsCompatibilityLaunchPolicy = Object.freeze({
  schema: 'swir.windows-compat-launcher/0.1',
  acceptedPlan: 'swir.windows-compat-launch/0.1',
  providers: ['swir.compat.wine', 'swir.compat.proton'],
  perAppPrefixRequired: true,
  shellExecution: false,
  environmentAllowlist: [...SAFE_ENV],
  windowsKernelDriversSupported: false
});
