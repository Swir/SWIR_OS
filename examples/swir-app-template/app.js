(() => {
  'use strict';

  const $ = selector => document.querySelector(selector);
  const status = $('#status');
  const note = $('#note');
  const STORAGE_KEY = 'starter.note';
  const LAUNCH_KEY = 'starter.launchCount';

  function setStatus(message, error = false) {
    status.textContent = message;
    status.classList.toggle('error', error);
  }

  function requireBridge() {
    const bridge = window.SwirAppBridge;
    if (!bridge?.sdk?.bridge?.info || !bridge?.sdk?.locale?.info || !bridge?.storage?.get || !bridge?.storage?.set) {
      throw new Error('SWIR App Bridge is unavailable. Open this package through a managed SWIR shell frame after catalog registration and permission approval.');
    }
    return bridge;
  }

  async function renderRuntime(bridge) {
    const [bridgeInfo, localeInfo, savedNote, savedLaunches] = await Promise.all([
      bridge.sdk.bridge.info(),
      bridge.sdk.locale.info(),
      bridge.storage.get(STORAGE_KEY, ''),
      bridge.storage.get(LAUNCH_KEY, 0)
    ]);

    const launchCount = Math.max(0, Number.parseInt(savedLaunches, 10) || 0) + 1;
    await bridge.storage.set(LAUNCH_KEY, launchCount);

    document.documentElement.lang = localeInfo?.locale || 'en';
    document.documentElement.dir = localeInfo?.direction === 'rtl' ? 'rtl' : 'ltr';

    $('#package-id').textContent = bridgeInfo?.packageId || bridge.packageId || 'unknown';
    $('#edition').textContent = bridgeInfo?.edition || 'unknown';
    $('#locale').textContent = `${localeInfo?.locale || 'en'} • ${document.documentElement.dir.toUpperCase()}`;
    $('#launches').textContent = await bridge.sdk.locale.formatNumber(launchCount);
    note.value = typeof savedNote === 'string' ? savedNote.slice(0, 120) : '';
    setStatus('Bridge ready. Storage access is permission checked by the host broker.');
  }

  async function start() {
    try {
      const bridge = requireBridge();
      await renderRuntime(bridge);

      $('#save').addEventListener('click', async () => {
        try {
          const value = note.value.trim().slice(0, 120);
          await bridge.storage.set(STORAGE_KEY, value);
          setStatus('Saved to the package app-data namespace.');
        } catch (error) {
          setStatus(error?.message || 'Save failed.', true);
        }
      });

      $('#clear').addEventListener('click', async () => {
        try {
          await bridge.storage.remove(STORAGE_KEY);
          note.value = '';
          setStatus('Private note cleared.');
        } catch (error) {
          setStatus(error?.message || 'Clear failed.', true);
        }
      });
    } catch (error) {
      setStatus(error?.message || 'Unable to initialize the SWIR SDK starter.', true);
    }
  }

  if (window.SwirAppBridge) start();
  else addEventListener('swir:app-bridge-ready', start, { once: true });
})();
