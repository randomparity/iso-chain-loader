# Rocky installer launcher

Rocky Linux 9.8 profiles hand off to Anaconda, interactive or, with login values, unattended.

## Modes

Instead of [Fedora](fedora.md), a manifest profile can select Rocky Linux 9.8, the newest Rocky
release that runs on POWER9. A `rocky`/`9.8` profile has a Fedora profile's fields without
`kickstart`, and its `repository.path` must end in `/BaseOS/ppc64le/os`. The launcher downloads and
checks the four pins and does not mount the launcher media. It then kexecs Anaconda with Fedora's
static network arguments and `inst.repo=`, and no `inst.ks=`, so the installer starts interactive
(ADR 0013). Anaconda first offers VNC or text mode; choose text. It fetches its `install.img`
runtime and adds the sibling AppStream repository from the same mirror, neither of them pinned, as
with [Fedora](fedora.md#modes).

## Example manifests

Use the [interactive](../../examples/rocky-interactive.json) or
[keyed unattended](../../examples/rocky-unattended.json) structural fixture;
[replace its synthetic values](building-media.md#synthetic-configuration-examples) before building.

## Verify the release

Trust starts from Rocky's signed `CHECKSUM`. Check it with the Rocky Enterprise Software
Foundation 2022 release key (`21CB256AE16FC54C6E652949702D426D350D275D`), and copy BaseOS's
`.treeinfo` and `repomd.xml`:

```sh
B=https://download.rockylinux.org/pub/rocky/9.8
mkdir -p "$HOME/iso-build/rocky/tree/repodata" && cd "$HOME/iso-build/rocky"
curl --fail -O "$B/isos/ppc64le/Rocky-9.8-ppc64le-boot.iso"
curl --fail -O "$B/isos/ppc64le/CHECKSUM" -O "$B/isos/ppc64le/CHECKSUM.asc"
curl --fail -O https://download.rockylinux.org/pub/rocky/RPM-GPG-KEY-Rocky-9
gpg --dearmor < RPM-GPG-KEY-Rocky-9 > rocky-9.gpg
gpgv --keyring ./rocky-9.gpg CHECKSUM.asc CHECKSUM
grep -F '(Rocky-9.8-ppc64le-boot.iso)' CHECKSUM
curl --fail -o tree/.treeinfo "$B/BaseOS/ppc64le/os/.treeinfo"
curl --fail -o tree/repodata/repomd.xml "$B/BaseOS/ppc64le/os/repodata/repomd.xml"
```

## Prepare the profile

`prepare-rocky-source` requires that digest. It requires the `.treeinfo` to name Rocky Linux 9.8
ppc64le `BaseOS`, to list the same digest for `images/boot.iso`, and to name
`../../../AppStream/ppc64le/os/` as the AppStream repository. It extracts the kernel and initrd
from the ISO, checks them against `.treeinfo`, and writes a `profile.json` that pins the mirror's
copies. It makes no network request and needs `xorriso`; on macOS run it in the build image, as
shown for [`prepare-fedora-source`](fedora.md#prepare-the-profile).

```sh
scripts/iso_chain.py prepare-rocky-source \
  --iso "$HOME/iso-build/rocky/Rocky-9.8-ppc64le-boot.iso" \
  --iso-sha256 bd0db737aeaede1817971cade75e72027dffe836ff983852ad940a6923775a70 \
  --tree "$HOME/iso-build/rocky/tree" \
  --repository-path /pub/rocky/9.8/BaseOS/ppc64le/os \
  --minimum-memory-mib 6400 --output "$HOME/iso-build/rocky-prepared"
```

## Memory floor

The installer itself started in 4,096 MiB of guest RAM, but the launcher needs `/run` space for the
257 MB kernel and initrd plus 1 GiB. Under QEMU pSeries POWER9, 6,144 MiB stops at the launcher's
`run-space` check and 6,656 MiB (`MemTotal` 6,529 MiB) reaches Installation Destination
(`docs/experiments/2026-10-02-rocky-installer.md`). Hence 6400, the passing arm's `MemTotal`
rounded down. A guest with a `MemTotal` from 6,400 through about 6,528 MiB passes that gate but may
still stop at `run-space`, so give the guest at least 6,656 MiB.

## Source tree and smoke stop point

`source` may be the Rocky mirror's origin or a local server. A local tree needs Rocky's paths
below `pub/rocky/9.8/`: BaseOS's `.treeinfo`, `images/install.img`, `ppc/ppc64/vmlinuz`,
`ppc/ppc64/initrd.img`, and `repodata/`, plus AppStream's `repodata/`. Check the four pins with
[`validate-external-source`](sources.md#validate-source-pins), then build and
[`smoke`](verification.md#installer-smoke-proof) with `--memory-mib 6656` or more. Stop at
Installation Destination; never begin the installation. Anaconda also requests
`images/updates.img` and `images/product.img`, which Rocky does not publish. The HTTP evidence
admits those two 404s, once each, for Rocky and for Fedora, whose tree omits them too. For Rocky it
otherwise allows only the four pins, then BaseOS and AppStream paths.
`verify-installer-evidence` reports `intended-source: operator-reviewed` for Anaconda's
Installation Source spoke.

## Unattended installation

When the manifest also carries `ssh_authorized_keys` and `login_user`, the Rocky profile installs
unattended instead (ADR 0019). `build` renders a Kickstart from the manifest and
`assets/kickstart/rocky-9.8-unattended.ks`, stages it as `/profiles/<profile>/ks.cfg`, and binds
its size and SHA-256 on the kernel command line, so the launcher mounts the media, checks the
Kickstart, and passes `inst.ks=cdrom:LABEL=...` beside `inst.repo=`. The Kickstart:

- creates the login user with no password and one `sshkey` line per key, each quoted with
  `shlex.quote`, and keeps root locked; the user gets no sudo rule or group (ADR 0023);
- in `%pre`, counts the non-optical disks as the launcher does and stops unless exactly one is
  present with zero first and last MiB, then partitions that disk by its live name with a PReP
  partition, `/boot`, and an LVM root, and installs GRUB with `--leavebootorder` so the firmware
  boot order keeps the ISO first;
- in `%post`, replaces every NetworkManager and `ifcfg` connection with one keyfile matching the
  manifest MAC, holding its address, routes, and DNS servers with IPv6 disabled, and sets the
  host name to `lpar`;
- in a last `%post`, after the user and keys exist, sets `iso_chain_installed=1` in
  `/boot/grub2/grubenv` (ADR 0021), then reboots, so the ISO's `installed disk` entry boots the new
  system. An install interrupted before that step stays on the Rocky entry, whose blank-disk guard
  refuses the disk. A disk installed from keyed Rocky media built before this marker existed needs
  `grub2-editenv /boot/grub2/grubenv set iso_chain_installed=1` before keyed media boots it.

`build` refuses a key starting with `-` and an `lpar` ending in `-`, which the Kickstart parser and
Anaconda cannot take. The installed packages come from the same unpinned BaseOS and AppStream
mirror, so a local tree also needs each repository's `Packages/` for the minimal environment.

Run these commands in the shell from [Build the ISO](building-media.md#build-the-iso), which sets
`umask 077` and `PRIVATE`. `install-rocky` takes the same arguments as
[`install-fedora`](verification.md#unattended-installation-proof), with defaults of 8,192 MiB, a
14,400-second install, and a 3,600-second boot, and requires a selected Rocky profile with login
values. Both QEMU runs attach the ISO first in the boot order, the fresh disk, and the manifest NIC,
each with its own capture, and pass `-no-reboot`. The first run ends when the Kickstart reboots; the
disk digest must have changed. The second boots that disk through the ISO's `installed disk` entry
and ends when the console shows `<lpar> login:`, when the harness stops QEMU. `result.json` records
`boot_stop: login-prompt` in place of `boot_exit_status`, and its `disk_sha256_after` is the disk as
the installer left it; the boot then writes the disk again. Filter both captures with the `tcpdump`
filter of the [unattended installation proof](verification.md#unattended-installation-proof), then:

```sh
scripts/iso_chain.py verify-rocky-install-evidence --record RECORD --config MANIFEST \
  --install-console-log "$PRIVATE/install/install-console.log" \
  --boot-console-log "$PRIVATE/install/boot-console.log" --access-log "$PRIVATE/access.jsonl" \
  --result "$PRIVATE/install/result.json" --install-pcap "$PRIVATE/install-forbidden.pcap" \
  --boot-pcap "$PRIVATE/boot-forbidden.pcap" \
  --disk-hash-before "$PRIVATE/disk-before.sha256" \
  --disk-hash-after "$PRIVATE/disk-after.sha256"
```

Its digest map binds `boot_pcap` in place of `kickstart`, since the manifest and the template at
the verifying commit determine the Kickstart; verify a run with the commit that built its ISO.
It requires one kernel `reboot: Restarting system` line and no `reboot: Power down` in the install
console; the launcher evidence with the derived `inst.ks=` and `inst.repo=`; HTTP
traffic of the four pins, then only BaseOS and AppStream paths with the two optional 404s; and a
boot console with one installed-disk handoff, no launcher, and the login prompt after it. The
[unattended Rocky experiment](../experiments/2026-10-02-rocky-unattended-install.md) records a
QEMU run, including an SSH login with the injected key; it is not native PowerVM evidence.

## Operator Kickstart

A Rocky profile can instead carry your own Kickstart in `operator_kickstart`
([ADR 0034](../adr/0034-carry-operator-installer-configuration-in-the-manifest.md)). Embed the
file in the manifest, replacing `kickstart` if you start from a prepared profile:

```sh
jq --rawfile text install.ks '.profiles.rocky.operator_kickstart = $text' base.json
```

Every profile in the manifest must then carry an operator file, and the manifest must carry no
`login_user`, `ssh_authorized_keys` or `install` values. `build` stages the composed file as
`/profiles/rocky/ks.cfg` and binds its size and SHA-256 on the kernel command line, so the
launcher hands off as it does for the derived Kickstart. The composition is a fixed `%pre` blank-disk
guard (exactly one non-optical disk, zero first and last MiB), your text unchanged, then a last
`%post` that sets `iso_chain_installed=1` in `/boot/grub2/grubenv`; the file may not exceed 1 MiB
once composed. The ISO's menu then boots only a marked disk.

The file owns users, root, privileges, host name, installed network and partitioning; the tool does
not read or check it. Install GRUB to the one disk, close every section with `%end`, end with
`reboot`, and keep the firmware boot order with `bootloader --leavebootorder`. The tool does not
police network or source commands, but passing evidence will need the file to fetch only from the
manifest source. The manifest and composed file carry the text
in the clear, so keep both private.
Check the manifest with [`validate-config`](building-media.md#validate-configuration-offline);
the [operator example](../../examples/rocky-operator.json) is a synthetic starting point. `validate-config` reads no
Kickstart syntax, and install evidence for operator media is not available yet (#130).

## Proof status

Each record has its own result and boundary sections:

- [Rocky installer VM experiment](../experiments/2026-10-02-rocky-installer.md): QEMU pSeries/POWER9,
  interactive.
- [Rocky unattended install VM experiment](../experiments/2026-10-02-rocky-unattended-install.md): QEMU
  pSeries/POWER9.
- [Rocky completion marker VM experiment](../experiments/2026-10-04-rocky-completion-marker.md): QEMU
  pSeries/POWER9.
- [Rocky preset customization VM experiment](../experiments/2026-10-26-rocky-preset-install.md): QEMU
  pSeries/POWER9.
- [FTP launcher installs and credential residue](../experiments/2026-10-27-ftp-installs-and-residue.md):
  QEMU pSeries/POWER9.

No Rocky record covers native PowerVM.

## Privacy and proof limits

Keep manifests, media, source trees, console logs, access logs, disk hashes and packet captures in
private storage (`umask 077`), using fresh output paths for every run, because they can contain
machine or network identifiers. Local checks and CI do not build or boot media. Emulator results
establish only their recorded QEMU boundary; native PowerVM requires separate proof.
