/* Trusted Update Center frame controller for SWIR Desktop Update User Policy 1.0 */
(() => {
  'use strict';
  if (window.top === window || location.origin !== parent.location.origin || location.pathname !== '/swir-updates.html') return;
  if (window.SWIR_UPDATE_POLICY_FRAME) return;

  const pending = new Map();
  let sequence = 0;
  let startupRunning = false;

  function policyApi() {
    try { return parent.SwirUpdatePolicy || null; } catch { return null; }
  }

  function nativeDesktop() {
    try { return policyApi()?.isDesktop?.() === true; } catch { return false; }
  }

  function command(method, timeoutMs = 15000) {
    return new Promise((resolve, reject) => {
      const id = `swir-policy-${Date.now()}-${++sequence}`;
      const timer = setTimeout(() => {
        pending.delete(id);
        const error = new Error('Desktop update policy command timed out.');
        error.code = 'UPDATE_BRIDGE_TIMEOUT';
        reject(error);
      }, timeoutMs);
      pending.set(id, { resolve, reject, timer });
      parent.postMessage({ type:'swir-system-update-command', id, method }, location.origin);
    });
  }

  window.addEventListener('message', event => {
    if (event.source !== parent || event.origin !== location.origin) return;
    const msg = event.data;
    if (!msg || msg.type !== 'swir-system-update-result' || !pending.has(msg.id)) return;
    const item = pending.get(msg.id);
    pending.delete(msg.id);
    clearTimeout(item.timer);
    if (msg.ok) item.resolve(msg.result);
    else {
      const error = new Error(msg.error?.message || 'Native update command failed.');
      error.code = msg.error?.code || 'NATIVE_HOST_ERROR';
      item.reject(error);
    }
  });

  function report(detail) {
    try { return policyApi()?.report?.(detail) === true; } catch { return false; }
  }

  function logPolicy(text) {
    const log = document.querySelector('#log');
    if (!log) return;
    log.textContent = `[POLICY ${new Date().toLocaleTimeString()}] ${text}\n` + log.textContent.slice(0, 2400);
  }

  function injectPolicyCard() {
    if (document.getElementById('swirUpdatePolicy')) return;
    const grid = document.querySelector('.grid');
    if (!grid) return;
    const card = document.createElement('div');
    card.className = 'card';
    card.id = 'swirUpdatePolicy';
    card.innerHTML = `
      <strong>Update behavior</strong>
      <span id="swirUpdatePolicySummary">Loading user policy…</span>
      <select id="swirUpdatePolicyMode" aria-label="Desktop update behavior" style="margin-top:9px;width:100%;border:1px solid var(--line);border-radius:9px;background:#061321;color:var(--text);padding:8px;font:800 9px ui-monospace,Consolas,monospace">
        <option value="automatic">AUTOMATIC — CHECK + PREPARE</option>
        <option value="notify">NOTIFY ONLY — CHECK, ASK BEFORE DOWNLOAD</option>
        <option value="manual">MANUAL — USER CHECK ONLY</option>
      </select>`;
    grid.appendChild(card);
    const select = card.querySelector('#swirUpdatePolicyMode');
    const summary = card.querySelector('#swirUpdatePolicySummary');
    const refresh = () => {
      const policy = policyApi()?.state?.();
      if (!policy) {
        summary.textContent = 'POLICY SERVICE UNAVAILABLE';
        select.disabled = true;
        return;
      }
      select.value = policy.mode;
      const desktop = policy.desktop ? 'DESKTOP ACTIVE' : 'SAVED FOR DESKTOP';
      const behavior = policy.mode === 'automatic'
        ? 'signed check + verified Candidate preparation; restart remains explicit'
        : policy.mode === 'notify'
          ? 'signed check only; download/install requires approval'
          : 'no automatic update network check';
      summary.textContent = `${desktop} • ${behavior}`;
    };
    select.addEventListener('change', () => {
      const result = policyApi()?.setMode?.(select.value);
      logPolicy(`User policy changed to ${String(result?.mode || select.value).toUpperCase()}.`);
      refresh();
    });
    try { parent.addEventListener('swir:update-policy-change', refresh); } catch {}
    refresh();
  }

  async function waitForPreparation(targetVersion) {
    const deadline = Date.now() + 5 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 1400));
      const snapshot = await command('preparationStatus', 12000);
      const state = String(snapshot?.preparation?.state || 'unknown');
      if (state === 'ready') {
        report({ status:'prepared', stage:'prepare', targetVersion });
        logPolicy(`Automatic Candidate preparation completed${targetVersion ? ` for ${targetVersion}` : ''}. Restart was not requested.`);
        return true;
      }
      if (state === 'failed') {
        report({ status:'failed', stage:'prepare', targetVersion, code:snapshot?.preparation?.error?.code || 'UPDATE_PREPARATION_FAILED' });
        logPolicy('Automatic Candidate preparation failed closed.');
        return false;
      }
      if (state === 'cancelled' || state === 'canceled') {
        report({ status:'failed', stage:'prepare', targetVersion, code:'UPDATE_PREPARATION_CANCELLED' });
        return false;
      }
    }
    report({ status:'failed', stage:'prepare', targetVersion, code:'UPDATE_PREPARATION_TIMEOUT' });
    logPolicy('Automatic Candidate preparation timed out without activation.');
    return false;
  }

  async function runStartupPolicy() {
    if (startupRunning) return;
    const api = policyApi();
    const request = api?.claimStartupRequest?.();
    if (!request || !nativeDesktop()) return;
    startupRunning = true;
    const mode = String(request.mode || 'manual');
    try {
      logPolicy(`Startup policy ${mode.toUpperCase()} started. Trust policy remains unchanged.`);
      let preparation = await command('preparationStatus', 12000);
      if (preparation?.feedConfigured !== true) {
        report({ status:'failed', stage:'check', code:'UPDATE_RELEASE_FEED_NOT_CONFIGURED' });
        logPolicy('Background signed check skipped because the release feed is not configured.');
        return;
      }

      const check = await command('check', 22000);
      if (check?.updateAvailable !== true) {
        report({ status:'current', stage:'check', targetVersion:check?.currentVersion || '' });
        logPolicy(`Signed startup check reports ${check?.currentVersion || 'installed version'} is current.`);
        return;
      }

      const targetVersion = String(check.targetVersion || '');
      if (mode === 'notify') {
        report({ status:'available', stage:'check', targetVersion });
        logPolicy(`Verified update ${targetVersion || 'available'} detected; Notify only policy did not download it.`);
        return;
      }
      if (mode !== 'automatic') return;

      let state = String(preparation?.preparation?.state || 'idle');
      if (state === 'ready') {
        report({ status:'prepared', stage:'prepare', targetVersion });
        logPolicy(`A verified Candidate is already prepared${targetVersion ? ` for target ${targetVersion}` : ''}.`);
        return;
      }
      if (state === 'failed') {
        await command('resetPreparation', 12000);
        preparation = await command('preparationStatus', 12000);
        state = String(preparation?.preparation?.state || 'idle');
      }
      if (state !== 'queued' && state !== 'running') {
        await command('prepare', 12000);
        logPolicy(`Automatic policy queued verified Candidate preparation for ${targetVersion || 'the signed update'}.`);
      }
      await waitForPreparation(targetVersion);
    } catch (error) {
      report({ status:'failed', stage:mode === 'automatic' ? 'prepare' : 'check', code:error?.code || 'NATIVE_HOST_ERROR' });
      logPolicy(`Policy action blocked: ${error?.code || 'NATIVE_HOST_ERROR'} • ${error?.message || 'unknown error'}`);
    } finally {
      startupRunning = false;
    }
  }

  window.SWIR_UPDATE_POLICY_FRAME = Object.freeze({
    schema:'swir.desktop-update-policy-frame/1.0',
    command,
    runStartupPolicy
  });

  const start = () => {
    injectPolicyCard();
    setTimeout(runStartupPolicy, 120);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once:true });
  else start();
})();