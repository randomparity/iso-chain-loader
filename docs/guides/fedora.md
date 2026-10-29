# Fedora installer launcher

Fedora 44 profiles carry a Kickstart on the launcher ISO and install from a pinned Fedora mirror.

## Modes

The ISO carries what this repository produces: the launcher, the manifest, and each profile's
Kickstart, about 100 MB in all. Everything Fedora publishes comes from the HTTPS mirror in the
manifest's `source`. The
[version 4 manifest](../workflow/specs/2026-10-01-iso-carried-artifacts-design.md#manifest-version-4)
names the Kickstart by media path under `/profiles/`. It pins Fedora's netinst kernel and
initrd, and the repository's `.treeinfo` and `repodata/repomd.xml`, by size and SHA-256.
The launcher downloads and checks those four files, then kexecs the installer. `build` labels the
ISO volume from the manifest digest, and Anaconda reads the Kickstart from the optical drive with
that label (`inst.ks=cdrom:LABEL=ISO_CHAIN_<digest prefix>:<path>`). It fetches its stage2 runtime,
`install.img`, from the mirror. No digest checks that runtime; use a mirror you trust. An `http://`
source also leaves the runtime unauthenticated in transit, so `build` and the launcher accept one
only on a loopback or RFC 1918 IPv4 address (ADR 0026).

## Example manifests

Start from [the Fedora structural fixture](../../examples/fedora.json); adapt it as described in
[synthetic configuration examples](building-media.md#synthetic-configuration-examples).

## Verify the release

Trust starts from Fedora's signed release. Download the Fedora 44 ppc64le netinst ISO and its
`CHECKSUM` file from the release's `iso/` directory, and check the signature inside the build image,
which ships Fedora's release keys:

```sh
B=https://dl.fedoraproject.org/pub/fedora-secondary/releases/44/Everything/ppc64le
mkdir -p "$HOME/iso-build/netinst" && cd "$HOME/iso-build/netinst"
curl --fail -O "$B/iso/Fedora-Everything-netinst-ppc64le-44-1.7.iso"
curl --fail -O "$B/iso/Fedora-Everything-44-1.7-ppc64le-CHECKSUM"
ENGINE=$(command -v podman || command -v docker)
"$ENGINE" run --rm -v "$PWD":/w:ro iso-chain-builder:44 sh -c \
  'gpg --batch --quiet --dearmor </etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-44-primary >/tmp/k.gpg &&
   gpgv --keyring /tmp/k.gpg --output /tmp/signed /w/Fedora-Everything-44-1.7-ppc64le-CHECKSUM &&
   cd /w && sha256sum -c --ignore-missing /tmp/signed && cat /tmp/signed'
```

Take the ISO's SHA-256 from the signed text that command prints, not from the downloaded file:
`gpgv` authenticates only the signed part, and lines outside it are not covered. Then copy the
two metadata files of the matching tree into a directory of their own:

```sh
mkdir -p "$HOME/iso-build/tree/repodata"
curl --fail -o "$HOME/iso-build/tree/.treeinfo" "$B/os/.treeinfo"
curl --fail -o "$HOME/iso-build/tree/repodata/repomd.xml" "$B/os/repodata/repomd.xml"
```

## Prepare the profile

`prepare-fedora-source` binds the two together and makes no network request. It requires the ISO
digest, requires the tree's `.treeinfo` to name Fedora 44 ppc64le (`Everything` or `Server`) and to
list that same digest for `images/boot.iso`, extracts the kernel and initrd from the ISO, and
requires each to match its `.treeinfo` checksum. It then writes the Kickstart and a `profile.json`
that pins the mirror's kernel and initrd to those sizes and digests.
`assets/kickstart/fedora-44-power9.ks` installs onto a QEMU guest's `vda`;
`assets/kickstart/fedora-44-powervm.ks` is the same unattended installation onto a PowerVM
partition's single vSCSI disk, `sda`. It needs `xorriso`; on macOS run it inside the build image.
The output path must not already exist.

```sh
R=$(pwd -P)   # this checkout
ENGINE=$(command -v podman || command -v docker)
"$ENGINE" run --rm --mount "type=bind,source=$R,target=$R,readonly" \
  --mount "type=bind,source=$HOME/iso-build,target=$HOME/iso-build" \
  iso-chain-builder:44 python3 "$R/scripts/iso_chain.py" prepare-fedora-source \
  --iso "$HOME/iso-build/netinst/Fedora-Everything-netinst-ppc64le-44-1.7.iso" \
  --iso-sha256 95e63afad3ea52af38940603a173ac4ea229db717549bcf607c5b7f3ced284ce \
  --tree "$HOME/iso-build/tree" \
  --repository-path /pub/fedora-secondary/releases/44/Everything/ppc64le/os \
  --kickstart KICKSTART --minimum-memory-mib MIB --output "$HOME/iso-build/prepared"
```

Copy `profile.json` into a private version 4 manifest whose `source` is the repository's origin,
here `https://dl.fedoraproject.org`. Fedora's primary release tree does not publish ppc64le; the
[Fedora 44 ppc64le mirror list](https://mirrors.fedoraproject.org/mirrorlist?repo=fedora-44&arch=ppc64le)
names other HTTPS mirrors of the same secondary tree. Any mirror whose kernel, initrd,
`.treeinfo`, and `repomd.xml` match the pinned bytes can be `source`; the launcher never falls back
to another. The shared `source` rules, including plain HTTP and FTP, are in
[source URL rules](sources.md#source-url-rules).

## Memory floor

No Fedora memory floor is stated. The unattended proof runs `install-fedora --memory-mib 32768`.

## Source tree and smoke stop point

Serve a full copy of the same Fedora tree, or use the pinned mirror, and run the
[installer smoke proof](verification.md#installer-smoke-proof). Stop with Ctrl-a x after the text
installer shows the intended source and disk, before beginning the installation.

## Unattended installation

Run `install-fedora` and `verify-fedora-install-evidence` as described in the
[unattended installation proof](verification.md#unattended-installation-proof).

The reference Kickstart intentionally targets only Fedora Server 44 and guest disk `/dev/vda`.
The install command mutates only the fresh disk it creates. Native PowerVM, HMC/VIOS mappings,
physical POWER9 storage, and other installer or storage layouts remain separate work.
The [manifest v4 installation experiment](../experiments/2026-10-03-fedora-v4-qemu-install.md)
records a QEMU run of this sequence against a local Fedora 44 Server tree; the earlier
[manifest v3 experiment](../experiments/2026-09-10-fedora-kickstart-install.md) records the
complete command sequence, controlled failures, and emulator boundary.

## Operator Kickstart

A Fedora profile can instead carry your own Kickstart in `operator_kickstart`
([ADR 0034](../adr/0034-carry-operator-installer-configuration-in-the-manifest.md)), in place of the
profile's `kickstart` artifact. Start from the
[starter Kickstart](../../assets/kickstart/fedora-44-operator-starter.ks), which is not the
reference Kickstart above, and embed your copy in the manifest:

```sh
jq --rawfile text install.ks '.profiles.fedora.operator_kickstart = $text' fedora.json
```

Every profile in the manifest must then carry an operator file, and the manifest must carry no
`login_user`, `ssh_authorized_keys` or `install` values. `build` stages the composed file as
`/profiles/<name>/ks.cfg` and binds its size and SHA-256 on the kernel command line. The
composition is a fixed `%pre` blank-disk guard (exactly one non-optical disk, zero first and last
MiB), your text unchanged, then a last `%post` that sets `iso_chain_installed=1` in
`/boot/grub2/grubenv`; the file may not exceed 1 MiB once composed. The ISO's menu then boots only a
marked disk.

You own what the file does. Replace the starter's placeholder user and key; the file owns users,
root, privileges, host name, installed network and partitioning, and the tool does not read or check
it. Install GRUB to the one disk, close every section with `%end`, end with `reboot` (not
`poweroff`), and keep the firmware boot order with `bootloader --leavebootorder`. The launcher
passes `inst.repo` from the manifest source, so the starter names no repository; add no `url` or
`repo` line that points elsewhere. The manifest and composed file carry the text in the clear, so
keep both private. Check the manifest with
[`validate-config`](building-media.md#validate-configuration-offline); it reads no Kickstart syntax,
and install evidence for operator media is not available yet (#130).

## Proof status

The [Fedora installer VM experiment](../experiments/2026-09-09-fedora-installer.md) reached the
Fedora 44 text installer with the intended local source, software selection, static interface, and
test disk visible. The backing disk digest stayed unchanged and the filtered capture contained no
DHCP or IPv6 packets. Native PowerVM was not run.

The earlier [static-launcher VM experiment](../experiments/2026-09-08-static-launcher.md) passed all five
arms: two configured defaults, a manual alternate profile, and missing/duplicate adapter failures.
It produced exactly three HTTP probes; all six captures were DHCP- and IPv6-free. Native PowerVM
was not run.

The earlier [optical/kexec experiment](../experiments/2026-09-08-power9-optical-bootstrap.md)
records a historical prototype; its build and smoke commands predate this manifest-based interface.

Other Fedora records, each with its own result and boundary sections:

- [PowerVM ISO-carried Kickstart installation](../experiments/2026-10-01-powervm-iso-carried-kickstart.md):
  native PowerVM.
- [PowerVM CAS reboot and installed-disk boot](../experiments/2026-10-17-powervm-cas-reboot.md): native
  PowerVM; read its proof limits before relying on it.
- [Installed-disk boot and blank-disk guard](../experiments/2026-10-02-installed-disk-boot.md): QEMU
  pSeries/POWER9.
- [FTP launcher installs and credential residue](../experiments/2026-10-27-ftp-installs-and-residue.md):
  QEMU pSeries/POWER9.

## Privacy and proof limits

Keep manifests, media, source trees, console logs, access logs, disk hashes and packet captures in
private storage (`umask 077`), using fresh output paths for every run, because they can contain
machine or network identifiers. Local checks and CI do not build or boot media. Emulator results
establish only their recorded QEMU boundary; native PowerVM requires separate proof.
