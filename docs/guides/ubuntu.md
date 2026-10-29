# Ubuntu installer launcher

Ubuntu 26.04.1 LTS profiles hand off to casper and subiquity, interactive or, with login values,
unattended.

## Modes

Instead of [Fedora](fedora.md), a manifest profile can select Ubuntu 26.04.1 LTS. The launcher
downloads and checks Ubuntu's netboot kernel and initrd, then kexecs casper with the manifest's
static IPv4 settings (`ip=...:off`, with the adapter chosen by `BOOTIF=<MAC>`) and `iso-url=` naming
the live-server ISO. casper downloads that ISO into RAM, boots its live system, and starts the
subiquity installer on the console. Nothing in the guest checks the ISO it downloads. casper's
BusyBox `wget` follows redirects and does not verify certificates, so serve it from a loopback or
controlled server you trust (ADR 0012). Subiquity's network screen then shows the adapter as static;
it may still contact the Ubuntu ports archive, NTP, and the snap store over the default route.

`ip=` carries one gateway and at most two DNS servers, so a manifest with an Ubuntu profile must
have only the default route and at most two DNS servers; any other shape fails at load.

## Example manifests

Use the [interactive](../../examples/ubuntu-interactive.json) or
[keyed unattended](../../examples/ubuntu-unattended.json) structural fixture;
[replace its synthetic values](building-media.md#synthetic-configuration-examples) before building.

## Verify the release

Trust starts from Ubuntu's signed `SHA256SUMS`. Fetch the ISO, `SHA256SUMS`, and
`SHA256SUMS.gpg`, and check the signature with the Ubuntu CD image signing key
(`843938DF228D22F7B3742BC0D94AA3F0EFE21092`). The `ubuntu-keyring` package installs it on Ubuntu
and Debian, and Fedora's `ubu-keyring` installs the same file:

```sh
B=https://cdimage.ubuntu.com/ubuntu/releases/26.04.1/release
mkdir -p "$HOME/iso-build/ubuntu" && cd "$HOME/iso-build/ubuntu"
curl --fail -O "$B/ubuntu-26.04.1-live-server-ppc64el.iso"
curl --fail -O "$B/SHA256SUMS" -O "$B/SHA256SUMS.gpg"
gpgv --keyring /usr/share/keyrings/ubuntu-archive-keyring.gpg SHA256SUMS.gpg SHA256SUMS
grep -F ' *ubuntu-26.04.1-live-server-ppc64el.iso' SHA256SUMS
```

## Prepare the profile

`prepare-ubuntu-source` requires that digest, requires the ISO's `.disk/info` to name Ubuntu-Server
26.04.1 LTS ppc64el, extracts `casper/vmlinux` and `casper/initrd`, and publishes them as
`netboot/ppc64el/linux` and `netboot/ppc64el/initrd` beside a `profile.json` that pins them and the
ISO under `--release-path`. They are byte-identical to the files `cdimage.ubuntu.com` serves under
the same path. It makes no network request and needs `xorriso`.

```sh
scripts/iso_chain.py prepare-ubuntu-source \
  --iso "$HOME/iso-build/ubuntu/ubuntu-26.04.1-live-server-ppc64el.iso" \
  --iso-sha256 3eb24626add663104f416bbdb3ca6ed37eabf8bb9a2308d4c9751d0976094826 \
  --release-path /ubuntu/releases/26.04.1/release \
  --minimum-memory-mib 5888 --output "$HOME/iso-build/ubuntu-prepared"
```

## Memory floor

`--minimum-memory-mib` is compared with the guest's `MemTotal`, which is below QEMU's `-m`. Under
QEMU pSeries POWER9, 6,144 MiB of guest RAM (`MemTotal` 6,019 MiB) is the smallest tested size that
reaches subiquity's storage screen; 4,096 MiB stops at the launcher's `/run` space check
(`docs/experiments/2026-10-02-ubuntu-installer.md`). Hence 5888.

## Source tree and smoke stop point

To serve it locally, lay out a directory with hard links to the verified ISO and the two
published files:

```text
TREE/ubuntu/releases/26.04.1/release/ubuntu-26.04.1-live-server-ppc64el.iso
TREE/ubuntu/releases/26.04.1/release/netboot/ppc64el/linux
TREE/ubuntu/releases/26.04.1/release/netboot/ppc64el/initrd
```

Serve `TREE` with [`serve-source`](verification.md#installer-smoke-proof), put the profile in a
manifest whose `source` is that server as the guest sees it, and check the three pins first with a
host-side copy of the manifest whose `source` the host can reach:

```sh
scripts/iso_chain.py validate-external-source --config HOST-MANIFEST --timeout-seconds 300
```

That command allows at most 300 s per artifact, so it needs about 5.5 MB/s to fetch the 1.6 GB ISO.
[Build](building-media.md#build-the-iso) and [`smoke`](verification.md#installer-smoke-proof) as
for Fedora with `--memory-mib 6144` or more. Stop at the guided storage screen,
declining any offered installer update. In the evidence record, `intended_source_confirmed` means
the operator saw subiquity's network screen show the matched adapter as `static` with the
manifest's address, and `verify-installer-evidence` reports it as
`installer-network: operator-reviewed`. The HTTP evidence must be exactly the kernel, initrd, and
ISO requests, once each. Under the snapshot overlay the disk hashes show only that the backing file
was untouched.

## Unattended installation

When the manifest also carries `ssh_authorized_keys` and `login_user`, the Ubuntu profile installs
unattended instead (ADR 0020). `build` renders cloud-init user data from the manifest and
`assets/autoinstall/ubuntu-26.04.1.json`, writes it as `/user-data` beside an empty `/meta-data` at
the ISO root, and binds its size and SHA-256 on the kernel command line. The launcher mounts the
media, refuses a second volume under the ISO's label in any case or as a FAT boot label, checks
both files, and adds `autoinstall ds=nocloud` and a `cc:` token that points cloud-init's NoCloud
datasource at the ISO's label. The user data is one JSON document after `#cloud-config`, so each
key is one quoted value. Its autoinstall configuration:

- creates the login user with no password, the manifest's keys, and no sudo rule or group
  (ADR 0023); no `identity` section exists, root stays locked, and the SSH server allows no
  password logins;
- in `early-commands`, counts the non-optical disks as the launcher does, stops unless exactly
  one is present with zero first and last MiB, and prints `autoinstall-disk: passed <disk>`; the
  `direct` storage layout then uses that disk;
- installs offline from the live ISO's packages, with no mirror, geoip mirror choice, installer
  refresh, or snaps; the installer still reaches geoip, the snap store, and NTS time servers, and
  the installed system keeps Ubuntu's default apt sources;
- writes a netplan configuration matching the manifest MAC with its address, default route, and
  DNS servers, and no DHCP or IPv6, and sets the host name to `lpar`; the installed kernel also
  gets `ipv6.disable=1` and masks networkd in its dracut initrd, which would otherwise run DHCP on
  every interface;
- ends with a late command that sets `iso_chain_installed=1` in the installed `grubenv`, then
  reboots. A keyed ISO's menu boots an installed disk only when that marker is set, so an
  install interrupted earlier stays on the installer entry, whose blank-disk guard refuses it.

`build` refuses an `lpar` ending in `-`, which is not a valid host name, `root` as the login user,
and a keyed manifest that mixes Rocky and Ubuntu profiles. Prepare the launcher initramfs from this
revision: an older launcher ignores the user-data arguments and starts the interactive installer.

`install-ubuntu` and `verify-ubuntu-install-evidence` take the same arguments and defaults as the
[Rocky commands](rocky.md#unattended-installation) and require a selected Ubuntu profile with login
values. Give the install `--memory-mib 8192` or more. The verifier makes the same checks, except
that the HTTP traffic must be exactly the kernel, initrd, and live ISO requests, the launcher
evidence must carry the whole unattended casper command line, and the install console must hold
`autoinstall-disk: passed <disk>` lines after the handoff that all name one disk, which only a run
that read the user data prints. Its second result line is `user-data: passed`. The [unattended
Ubuntu experiment](../experiments/2026-10-03-ubuntu-unattended-install.md) records a QEMU run, an
SSH login with the injected key, and an interrupted install; it is not native PowerVM evidence.

## Operator user data

An Ubuntu profile can instead carry your own autoinstall in `operator_user_data`
([ADR 0034](../adr/0034-carry-operator-installer-configuration-in-the-manifest.md)). The text is
`#cloud-config` followed by one JSON object whose only key is `autoinstall`; embed it in the
manifest:

```sh
jq --rawfile text user-data '.profiles.ubuntu.operator_user_data = $text' base.json
```

The manifest must carry exactly one profile and no `login_user`, `ssh_authorized_keys` or `install`
values. Numbers must be integers, keys at most 1,000 characters once serialised, and nesting at most
64 levels, so that cloud-init reads the document as the JSON it is. `build` stages the composed
document as `/user-data` beside an empty `/meta-data` and binds its size and SHA-256 on the kernel
command line, as for the derived user data. The composition puts the blank-disk guard (exactly one
non-optical disk, zero first and last MiB) first in `early-commands` and the `grubenv` completion
marker last in `late-commands`, your other keys and commands unchanged; the document may not exceed
1 MiB once composed. The ISO's menu then boots only a marked disk.

The file owns accounts, privileges, host name, installed network, storage and the mirror policy; the
tool does not read or check them. Write the guest network yourself, matching the manifest MAC with
static IPv4 and no DHCP, set `shutdown: reboot`, and keep the installer offline as the derived data
does. The manifest and composed file carry the text in the clear, so keep both private. Check the
manifest with [`validate-config`](building-media.md#validate-configuration-offline); the
[operator example](../../examples/ubuntu-operator.json) holds the derived unattended answers minus
their guard and marker, as a synthetic starting point. [Install evidence for operator media](verification.md#operator-file-media)
stops at the installed-disk handoff.

## Proof status

Each record has its own result and boundary sections:

- [Ubuntu installer VM experiment](../experiments/2026-10-02-ubuntu-installer.md): QEMU pSeries/POWER9,
  interactive.
- [Ubuntu unattended install VM experiment](../experiments/2026-10-03-ubuntu-unattended-install.md): QEMU
  pSeries/POWER9.
- [Ubuntu preset customization VM experiment](../experiments/2026-10-26-ubuntu-preset-install.md): QEMU
  pSeries/POWER9.
- [FTP launcher installs and credential residue](../experiments/2026-10-27-ftp-installs-and-residue.md):
  QEMU pSeries/POWER9.
- [Operator-file launcher installs](../experiments/2026-10-29-operator-file-installs.md): QEMU
  pSeries/POWER9, stopped at the installed-disk handoff.

No Ubuntu record covers native PowerVM.

## Privacy and proof limits

Keep manifests, media, source trees, console logs, access logs, disk hashes and packet captures in
private storage (`umask 077`), using fresh output paths for every run, because they can contain
machine or network identifiers. Local checks and CI do not build or boot media. Emulator results
establish only their recorded QEMU boundary; native PowerVM requires separate proof.
