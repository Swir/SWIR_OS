const PROVIDERS = Object.freeze({
  'swir.package.system': Object.freeze({
    executionClass: 'linux-native',
    capability: 'system-package-manager',
    sourceClasses: ['distribution-repository', 'vendor-official-repository', 'swir-signed'],
    privilegedMutation: true
  }),
  'swir.package.flatpak': Object.freeze({
    executionClass: 'linux-native',
    capability: 'flatpak',
    sourceClasses: ['flatpak-remote', 'swir-signed'],
    privilegedMutation: true
  }),
  'swir.package.appimage': Object.freeze({
    executionClass: 'linux-native',
    capability: 'appimage',
    sourceClasses: ['swir-signed', 'local-user-selected'],
    privilegedMutation: false
  }),
  'swir.compat.wine': Object.freeze({
    executionClass: 'windows-compat',
    capability: 'wine',
    sourceClasses: ['swir-signed', 'distribution-repository', 'vendor-official-repository', 'local-user-selected'],
    privilegedMutation: false
  }),
  'swir.compat.proton': Object.freeze({
    executionClass: 'windows-compat',
    capability: 'proton',
    sourceClasses: ['swir-signed', 'distribution-repository', 'vendor-official-repository', 'local-user-selected'],
    privilegedMutation: false
  })
});

const SYSTEM_PACKAGE_MANAGERS = new Set(['apt', 'dnf', 'rpm-ostree', 'pacman', 'zypper']);

function assertObject(value, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${name} must be an object`);
}

export function normalizeProviderCapabilities(host = {}) {
  const packageManagers = Array.isArray(host?.capabilities?.packageManagers)
    ? host.capabilities.packageManagers.filter(name => SYSTEM_PACKAGE_MANAGERS.has(name))
    : [];
  const tools = host?.capabilities?.tools && typeof host.capabilities.tools === 'object'
    ? host.capabilities.tools
    : {};
  return Object.freeze({
    'system-package-manager': packageManagers.length > 0,
    flatpak: tools.flatpak === true,
    appimage: tools.appimage === true,
    wine: tools.wine === true,
    proton: tools.proton === true,
    packageManagers: Object.freeze([...packageManagers])
  });
}

export function resolveSystemPackageProvider(manifest, host = {}) {
  assertObject(manifest, 'package manifest');
  if (manifest.schema !== 'swir.package-provider/0.2') throw new Error('unsupported package provider schema');
  if (!Array.isArray(manifest.targetEditions) || !manifest.targetEditions.includes('system')) throw new Error('package does not target System Edition');
  const definition = PROVIDERS[manifest.provider];
  if (!definition) throw new Error('provider is not available to System Edition');
  if (manifest.executionClass !== definition.executionClass) throw new Error('provider executionClass mismatch');
  if (manifest.trust?.signatureRequired !== true) throw new Error('System Edition provider requires signature verification');
  if (!definition.sourceClasses.includes(manifest.trust?.sourceClass)) throw new Error('provider sourceClass is not allowed');

  const capabilities = normalizeProviderCapabilities(host);
  const available = capabilities[definition.capability] === true;
  return Object.freeze({
    schema: 'swir.package-provider-plan/0.1',
    mode: 'preview',
    readOnly: true,
    autoExecutable: false,
    packageId: manifest.id,
    provider: manifest.provider,
    executionClass: manifest.executionClass,
    sourceClass: manifest.trust.sourceClass,
    requiredCapability: definition.capability,
    capabilityAvailable: available,
    status: available ? 'ready' : 'unavailable',
    packageManagers: capabilities.packageManagers,
    privilegedMutation: definition.privilegedMutation,
    privilegedMutationRequiresPlan: true,
    privilegedMutationRequiresJournal: true,
    signatureVerificationRequired: true
  });
}

export function listSystemPackageProviders() {
  return Object.entries(PROVIDERS).map(([id, definition]) => ({
    id,
    executionClass: definition.executionClass,
    capability: definition.capability,
    sourceClasses: [...definition.sourceClasses],
    privilegedMutation: definition.privilegedMutation
  }));
}

export const SystemPackageProviderPolicy = Object.freeze({
  schema: 'swir.package-provider-registry/0.1',
  providerIds: Object.freeze(Object.keys(PROVIDERS)),
  systemPackageManagers: Object.freeze([...SYSTEM_PACKAGE_MANAGERS]),
  webProviderAllowed: false,
  readOnlyPlanning: true,
  privilegedMutationRequiresPlan: true,
  privilegedMutationRequiresJournal: true,
  signatureVerificationRequired: true,
  arbitraryDriverDownloads: false,
  windowsKernelDriversAsLinuxDrivers: false
});
