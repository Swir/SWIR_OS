/* SWIR OS 1.1 runtime loader — corrected build + appearance engine + bundled application i18n */
(() => {
  const queue = [
    './swir-theme-engine.js?v=1.0.0',
    './swir-v11-fixed.js?v=1.1.1',
    './swir-app-locales-west.js?v=0.1.0',
    './swir-app-locales-global.js?v=0.1.0',
    './swir-app-locales-world.js?v=0.1.0',
    './swir-app-locales-system.js?v=0.2.0',
    './swir-app-i18n-host.js?v=0.2.0'
  ];
  for (const src of queue) {
    const script = document.createElement('script');
    script.src = src;
    script.async = false;
    document.head.appendChild(script);
  }
})();