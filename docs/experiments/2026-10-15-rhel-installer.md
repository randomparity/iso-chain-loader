# RHEL Installer PowerVM Experiment

Date: 2026-10-15 (runs ended 2026-10-16 UTC)

## Result

One POWER9 PowerVM partition (`lpar-R1` on `sys-R1`, HMC `hmc-R1`, VIOS `vios-R1`) booted the
optical launcher for RHEL 9.8 and for RHEL 10.2. Each run passed the launcher's `configuration`,
`adapter-match`, `profile`, `memory`, `disk`, and `artifacts` gates from an authenticated
`ftp://` source, then `kexec-load: passed` and `kexec-exec: started`, and kexeced into the
release's Anaconda with no Kickstart:

| Release | Installer kernel | Anaconda | Hub result |
| --- | --- | --- | --- |
| 9.8 | 5.14.0-687.5.3.el9_8 | 34.25.7.14-1.el9 | source and software selection resolved |
| 10.2 | 6.12.0-211.7.3.el10_2 | 40.22.3.46-1.el10_2 | source and software selection resolved |

At the text-mode prompt (VNC on 9.8, RDP on 10.2) the operator chose text mode. On both releases
the hub then showed Installation source as the release's `BaseOS/ppc64le/os` tree,
Software selection as "Server with GUI", and Network configuration as `Connected: iso0`. The
operator counted case-insensitive `appstream` matches in `/tmp/packaging.log` from Anaconda's
shell: 10 on 9.8 and 23 on 10.2. `/tmp/anaconda.log` held none on 9.8 and was not counted on
10.2. The packaging counts show that Anaconda's packaging layer saw an AppStream repository, which
`inst.addrepo` supplies; the hub does not name it.

RHEL 10 booted and reached its hub on POWER9 hardware, so the 10.x profiles have a live proof for
10.2 only. No other release was run.

The operator installed the 9.8 system to completion after the hub check, a step beyond the plan,
and I observed only its console: GRUB 2.06 offered the installed RHEL 9.8 (Plow) entry, the
5.14.0-687.5.3.el9_8 kernel booted, and the console reached a login prompt, with the address
answering ping. I did not inspect the installed system, so this records an installation reaching
a login prompt and nothing about its contents.

## Inputs and environment

- **Partition.** POWER9 processor mode (`POWER9_Base`), 12 GiB memory, 0.5 processing units, 2
  virtual processors, one virtual Ethernet adapter bridged by a shared Ethernet adapter, a 50 GiB
  vSCSI logical volume, and a virtual optical device on a second vSCSI client adapter.
- **Tooling.** The partition was created, mapped, powered, and given media with `hmcpctl`.
  Console evidence came from `hmcpctl lpars capture-console`, and the operator used their own
  console terminal for the Anaconda prompts and shell.
- **Media.** `container-build` built each ISO from the `feat/rhel-profiles-78` branch; the branch
  head when this record was written was `f80001e`. The launcher kernel was Fedora 7.2.10-200.fc44
  and its initramfs came from `container-prepare-initramfs`. Both ISOs are 109,860,864 bytes:
  - 9.8: `7fab0d4fc78f2a0831c95f95d73685afb61a13ec129336cbd6a7d41ee26dc110`;
  - 10.2: `000c9d394ecb0686608967e9cf358a4b7eba9d5f4a8e4f12402dd1e4fd735c47`.
- **Source.** An authenticated `ftp://` mirror. `prepare-rhel-source` took each boot ISO's digest
  from the mirror's unsigned `*.SHA256SUM` under `--digest-source mirror-sha256sum`:
  - 9.8: `RHEL-9.8.0-updates-20260511.3-ppc64le-boot.iso`, 1,490,919,424 bytes,
    `af98bc6e84125199cb3d8ee0e848d9f2f96ba3ac3a7e904f9a9e2d013253e2eb`;
  - 10.2: `RHEL-10.2-updates-20260511.1-ppc64le-boot.iso`, 1,020,456,960 bytes, SHA-256
    `0b61f28c67fba0db47c25c8d0b4c70560a080ccb7ae1c1c887e23f2a26bf9ebe`.
- **Pinned artifacts.** Paths below `<REDACTED-PATH-PREFIX>/RHEL-<release>-GA/BaseOS/ppc64le/os`:
  - 9.8 `vmlinuz` 47,225,727 bytes
    `0d14aea3c4558fcb83b8d3c81561ee267c3a1bd81af2e432578c281e5b8e7f7a`, `initrd.img` 211,931,476
    bytes `75998e6d4d6affdf54ba7217318aa474979453d21a5254b39d8e80834ab0d9d7`, `.treeinfo` 1,096
    bytes `73400bf55eebf92c395bfb1e3f1052c9cacad4fc2c4d7dd22c7f55de3ac33f05`, `repomd.xml` 2,815
    bytes `ec861e7a02707ec0a953326ac497879daadf7f5039dd72a821b8c94758620a2a`;
  - 10.2 `vmlinuz` 48,622,727 bytes
    `538ca45b64b64f178256870c8c56e5c1efb64fb23ee0a642921e45e2b4a3d63b`, `initrd.img` 203,570,952
    bytes `d1a0a610df4026e58957aac4caf84d2d363f6eeba8d34c9be385ebd4d56c4b4d`, `.treeinfo` 1,098
    bytes `03cf1cd687064c0c0df674e4062193924e6175920c4f957c926d60bec725f10b`, `repomd.xml` 2,815
    bytes `3222bac025a1de16f9ff071a07552b197ada1d7f2ba965d0065365de0bdd683d`.
- **Retained private evidence, by SHA-256.** The 9.8 boot console
  `1ed3e35bc29be0d19472016d1e3e8b9ee75aed6b0e5597f9ae84c877bad745ef` and the 10.2 boot console
  `2e86d330155bb984d059bbe4792ea14cd65d08be732dffcb06282ffc31557194`. Manifests, consoles, and the
  ISOs stay in mode-0700 private storage.

`verify-launcher-log` and the `verify-*-install-evidence` commands were not run against these
consoles: the source was FTP, so no HTTP access log or packet capture exists, and the consoles
come from bounded `capture-console` windows rather than a `smoke` or install run.

## Findings

- **Stale disk stalled GRUB.** The first 9.8 power-on printed "Welcome to GRUB!" and then nothing.
  A later boot of a variant ISO with its `grubenv` search loop removed showed the GRUB menu entry
  `installed-disk handoff` repeating 31 times with `no server is specified`, which that ISO does
  not contain, and then the launcher's `disk-blank: failed`. I take this to be GRUB reading a
  leftover `grub.cfg` from reused extents of the new logical volume; I did not inspect the
  extents. After the operator zeroed the first and last MiB, the unmodified ISO passed the `disk`
  gate. The blank-disk guard of ADR 0018 did what it is for, and no defect in this branch was
  found.
- **A zeroed disk still costs a long GRUB wait.** On both releases GRUB printed
  `grub_search_fs_file ... no such device:` for the `grubenv` paths of ADR 0018's search loop, and
  the console stayed silent for many minutes before the menu. On 10.2, GRUB reached its menu,
  booted the `rhel` entry, and after the firmware's CAS reboot printed "Welcome to GRUB!" and
  searched again. From power-on to the first answered ping took about 75 minutes on 10.2
  (13:57Z to between 15:12Z and 15:15Z, from polls three minutes apart). The 9.8 run was not
  timed. The cause is not established: it may be GRUB probing an empty vSCSI disk, but I did not
  test that. This is independent of the RHEL profiles and is not fixed here.
- **Anaconda prints the FTP credential.** The hub's Installation source line shows the `ftp://`
  URL with its userinfo on both releases. ADR 0016 records that exposure; this run observed it on
  a real console.
- **Boot order.** Installing the 9.8 system set the firmware boot list to the installed disk, so
  the 10.2 boot first booted the installed 9.8 system. The disk was zeroed, the boot order was set
  to the optical device again, and the 10.2 launcher then booted.

## Boundary and cleanup

Mutations stayed within the partition I created, its VIOS mappings, and the VIOS media
repository. The operator authorized deleting two unrelated older test ISOs in that repository and
zeroing the partition's disk twice. The installed disk is a test artifact. No other release,
subscription registration, or Kickstart was exercised.
