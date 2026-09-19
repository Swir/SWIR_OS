# SWIR Driver Center Runtime 0.1

Status: **implemented diagnostics runtime / privileged mutations remain separate transaction flows**

`system/hardware/driver-center-runtime.mjs` composes the existing read-only Hardware Service, Hardware Catalog, preview-only Driver Resolver, Driver Center safety policy and read-only fwupd/LVFS discovery into one System Edition diagnostics surface. `driver-center-cli.mjs` exposes that surface for the booted image without giving applications raw package-manager, driver-loader, firmware-update or shell access.

## Runtime path

```text
Linux /sys PCI + USB inventory
        |
        v
Hardware Service
        |
        +--> bound module / modalias / PCI+USB IDs
        |
        v
Hardware Catalog
        |
        +--> kernel-in-tree
        +--> linux-firmware
        +--> distribution repository
        +--> fwupd/LVFS
        +--> allowlisted vendor repository
        |
        v
Driver Resolver (preview only)
        |
        v
Driver Center diagnostics
        |
        +--> health / attention / unknown
        +--> proposed operations
        +--> rollback metadata
        +--> zero trust-policy violations required
        |
        +--> fwupd/LVFS read-only update inventory
```

## Safety model

- unknown hardware never triggers an automatic download;
- arbitrary driver URLs remain forbidden;
- Windows kernel drivers are not treated as Linux drivers;
- repository signatures are required by policy;
- every future privileged mutation must have a structured plan and journal;
- the runtime is `readOnly=true` and `autoMutation=false`;
- fwupd integration only exposes signed LVFS discovery here and never pre-authorizes installation;
- an unavailable/offline fwupd inventory is reported as diagnostics state rather than weakening trust checks;
- the CLI refuses symlink output targets and writes evidence mode `0600`.

## Contract and host-visibility proof

The dedicated Driver Center contract always runs the complete deterministic Hardware Service, catalog, resolver, Driver Center, fwupd/LVFS and runtime self-test suite. It then executes the production CLI against the hosted runner's actual Linux sysfs and requires the diagnostics/read-only/mutation-policy invariants regardless of how much hardware the host exposes.

Hosted CI hardware visibility is an environment property, not a product invariant. Before the production probe the workflow checks `/sys/bus/pci/devices/*` explicitly. If PCI devices are visible, the runtime must observe at least one real PCI device. If the hosted runner exposes zero PCI devices, the runtime must report zero PCI devices; the workflow records that limitation in the job summary and **does not fabricate a device, a bound driver, live-hardware evidence or a hardware-qualification claim**. This keeps the safety/runtime contract deterministic without weakening the separate live-hardware gate.

`System Hardware Live E2E` remains the stronger live-environment lane. It executes the production Hardware Service only when the runner actually exposes PCI sysfs inventory and then requires PCI inventory, a loaded kernel driver, zero Driver Center policy violations and `hardwareQualificationClaim=false`. A no-PCI hosted runner is reported as unavailable evidence, not converted into synthetic proof. Physical-machine qualification remains separate from both hosted-runner lanes.

The Hardware Catalog includes the QEMU virtio block path used by the System Edition boot lane and keeps source classes limited to controlled Linux sources. The NVIDIA vendor source also carries an explicit repository identity so it cannot become a latent policy violation when matching real hardware.

## Roadmap interpretation

Once the exact revision passes the Driver Center contract and the existing live Hardware Service gate on an environment that exposes qualifying kernel sysfs inventory, the scoped **SWIR Driver Center / Hardware Catalog** deliverable is implemented: real PCI/USB IDs are mapped to controlled support/source metadata, loaded-driver status is visible, proposed package/firmware operations carry rollback metadata, fwupd/LVFS update availability is surfaced read-only when available, and diagnostics remain fail-closed.

Separate roadmap items remain open for actual driver/firmware mutation transactions, production fwupd update/reboot/recovery, vendor repository onboarding and broad physical hardware qualification.
