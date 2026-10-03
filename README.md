ISO Chain Loader
================

A ppc64le optical launcher with a GRUB profile menu, per-system static IPv4 settings, verified
Fedora installer and Kickstart carried on the ISO itself, a pinned public Fedora repository, and
a kexec handoff to the text installer. A profile can instead hand off to the Rocky Linux 9.8 text
installer, interactive or, with SSH keys and a login user in the manifest, unattended; the
openSUSE Leap 15.6 linuxrc and YaST installer; or the Ubuntu 26.04.1 live-server installer,
interactive or, with SSH keys and a login user, unattended.

Development
-----------

Development is supported on macOS arm64 and on x86_64 Linux, with Python 3.14,
just 1.57 or newer, and uv 0.12.12 or a compatible release. uv provides Python
3.14 when the host does not already have it. Set up the isolated Python
environment and install the Git hook:

```sh
just setup
```

Run the same aggregate checks used by continuous integration:

```sh
just check
```

The check command, local hooks, and continuous integration do not modify repository files. Apply
safe Python and Markdown fixes explicitly, then run the full checks, with:

```sh
just fix
```

The installed pre-commit hooks run the focused checks when committing. To run
all configured hooks directly, use:

```sh
.venv/bin/pre-commit run --all-files
```

Secret checks compare current tracked content with the reviewed `.secrets.baseline`; updating that
baseline is a separate review action. Python type checking will be added when the repository has
explicit Python source paths.

The ISO output targets ppc64le. Building bootable media additionally requires
ppc64le-capable GNU binutils, GRUB image tooling, and `xorriso`; `just setup`
does not install these target build tools.

End-to-end validation requires either a ppc64le emulator or a real ppc64le
system. The local checks and continuous integration workflow do not build or
validate bootable media.

Building the launcher ISO on macOS
----------------------------------

macOS does not provide `grub2-mkrescue` or `xorriso` for the `powerpc-ieee1275`
target. `container-build` runs the same `build` implementation inside a pinned
Fedora image instead, using `podman` when it is on `PATH` and `docker`
otherwise; `--engine NAME` selects one explicitly. Build the image once, then
build the ISO:

```sh
just build-image
mkdir -p "$HOME/iso-build"
.venv/bin/python scripts/iso_chain.py container-build --config MANIFEST \\
  --kernel FILE --initramfs FILE --profiles DIR --output "$HOME/iso-build/launcher.iso"
```

`container-build` mounts the repository tree read-only and the directory holding each path argument
at its own absolute path inside the container — read-only, except the output directory, which is
writable — so the engine's file sharing must reach the manifest, the kernel, the initramfs, the
profile directory, and the output directory, and the output directory must already exist. Every
other file in those directories
is visible to the container, and when the output directory also holds an input, that input sits in a
writable mount and is protected by the build implementation rather than by the mount. The output
directory must not be the repository root itself, because the repository's own mount would then have
to be writable; an output directory inside or above the repository is mounted separately, and the
deeper mount wins. A mount source containing a comma is rejected before any container starts. The
image carries the packaged `powerpc-ieee1275` GRUB modules, so `--grub-modules` is optional and
defaults to the image's module directory; pass it to use a different module set.

The image lives in the detected engine's own image store, so build it with the same engine that
builds the ISO: `just build-image` detects the engine the same way, and `container-build` names the
exact build command in its error when the image is missing.

The ISO is written by the container process. With the engine verified here (Docker Desktop on
macOS) it belongs to the invoking user; a rootful engine can create it as `root` inside the shared
mount, so check `ls -l` after the first build and correct ownership if a later step must read it as
another user.

Inspect an ISO inside the same image. Its directory must be mounted writable,
because `inspect` extracts the embedded manifest into a temporary directory
beside the ISO:

```sh
ENGINE=$(command -v podman || command -v docker)
"$ENGINE" run --rm \
  --mount type=bind,source=REPO,target=REPO,readonly \
  --mount type=bind,source=ISO-DIR,target=ISO-DIR \
  iso-chain-builder:44 python3 REPO/scripts/iso_chain.py inspect ISO-DIR/launcher.iso
```

`smoke`, `install-fedora`, `install-rocky`, and `install-ubuntu` still require ppc64le QEMU and do
not run on macOS.

Building the launcher initramfs on macOS
----------------------------------------

`prepare-initramfs` runs dracut against an installed ppc64le kernel, so it needs a ppc64le host.
`container-prepare-initramfs` runs it inside `iso-chain-initramfs:44`, an image built for
`linux/ppc64le` from `Containerfile.initramfs` with the same pinned Fedora 44 base as the ISO build
image. It publishes the image's kernel and the launcher initramfs built for it into an existing
directory that does not already hold `vmlinuz` or `initramfs.img`:

```sh
just build-initramfs-image
mkdir -p "$HOME/iso-build/launcher"
.venv/bin/python scripts/iso_chain.py container-prepare-initramfs \
  --output-dir "$HOME/iso-build/launcher"
```

On a non-ppc64le host the engine emulates ppc64le, which is slow: about two minutes for the image
and one for the initramfs on Docker Desktop for macOS arm64, the verified host. Podman needs
`qemu-user-static` inside its machine, and Docker on Linux needs a registered ppc64le
`binfmt_misc` handler; neither has been verified here. The launcher initramfs carries the virtio
drivers for QEMU and `ibmveth`, `ibmvscsi`, `sr_mod`, and `isofs` for PowerVM partitions.

On a ppc64le Linux host with Python 3.14, dracut, systemd, iproute, curl, and the matching kernel
modules, run the same step directly:

```sh
sudo python3 scripts/iso_chain.py prepare-initramfs --kernel-version VERSION --output FILE
```

Fedora installer launcher
-------------------------

The ISO carries what this repository produces: the launcher, the manifest, and each profile's
Kickstart, about 100 MB in all. Everything Fedora publishes comes from the HTTPS mirror in the
manifest's `source`. The
[version 4 manifest](docs/workflow/specs/2026-10-01-iso-carried-artifacts-design.md#manifest-version-4)
names the Kickstart by media path under `/profiles/`. It pins Fedora's netinst kernel and
initrd, and the repository's `.treeinfo` and `repodata/repomd.xml`, by size and SHA-256.
The launcher downloads and checks those four files, then kexecs the installer. `build` labels the
ISO volume from the manifest digest, and Anaconda reads the Kickstart from the optical drive with
that label (`inst.ks=cdrom:LABEL=ISO_CHAIN_<digest prefix>:<path>`). It fetches its stage2 runtime,
`install.img`, from the mirror. No digest checks that runtime; use a mirror you trust, over HTTPS
unless it is a loopback or controlled test server, since an `http://` source also leaves the runtime
unauthenticated in transit.

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

`prepare-fedora-source` binds the two together and makes no network request. It requires the ISO
digest, requires the tree's `.treeinfo` to name Fedora 44 ppc64le (`Everything` or `Server`) and to
list that same digest for `images/boot.iso`, extracts the kernel and initrd from the ISO, and
requires each to match its `.treeinfo` checksum. It then writes the Kickstart and a
`profile.json` that pins the mirror's kernel and initrd to those sizes and digests. `assets/kickstart/fedora-44-power9.ks`
installs onto a QEMU guest's `vda`; `assets/kickstart/fedora-44-powervm.ks` is the same unattended
installation onto a PowerVM partition's single vSCSI disk, `sda`. It needs `xorriso`; on macOS
run it inside the build image. The output path must not already exist.

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
`.treeinfo`, and `repomd.xml` match the pinned bytes can be `source`; the launcher never falls
back to another. `source` must be `http://` or `https://`: authenticated FTP sources are not
accepted yet (ADR 0016, issue #37).

Before booting, check the origin without modifying it:

```sh
scripts/iso_chain.py validate-external-source --config MANIFEST \
  --profile PROFILE --timeout-seconds 30
```

The command requests the four pinned files (kernel, initrd, `.treeinfo`, and `repomd.xml`) and
requires HTTP 200, the exact streamed byte count
(with either `Content-Length` or chunked responses), and the manifest's SHA-256. HTTPS uses the
system certificate and hostname checks; redirects, credentials, queries, and fragments are
rejected. Mirror errors are not retried: `dl.fedoraproject.org` has answered transient 404s, and a
failed request fails the check, or the boot, until it is run again. An opt-in test runs the same
check when `ISO_CHAIN_EXTERNAL_MIRROR` and `ISO_CHAIN_EXTERNAL_MANIFEST` are set; there is no
implicit URL or fallback mirror.

Build the ISO from the launcher payload, its kernel, the prepared profile directory, and the
manifest. `build` checks every profile artifact against the manifest before staging it on the
ISO; `inspect` returns the embedded manifest's canonical JSON. Keep manifests, media, source trees,
console logs, access logs, disk hashes, and packet captures in private storage because they can
contain machine or network identifiers. Each ISO binds one partition's network, so expect one
ISO of about 100 MB per partition.

```sh
umask 077
PRIVATE=$(mktemp -d)
.venv/bin/python scripts/iso_chain.py container-build --config MANIFEST \
  --kernel "$HOME/iso-build/launcher/vmlinuz" \
  --initramfs "$HOME/iso-build/launcher/initramfs.img" \
  --profiles "$HOME/iso-build/prepared" --output "$HOME/iso-build/launcher.iso"
```

A local QEMU run can serve the repository itself instead: hold a full copy of the same Fedora tree,
serve it with `serve-source`, and set `source` and `repository.path` to that server. The
bundled server writes the JSONL access log that the evidence verifiers read; an ordinary external
web server's logs must be adapted to its `method`, `path`, `status`, `bytes`, and monotonic `index`
fields, a weaker evidence boundary.

```sh
scripts/iso_chain.py serve-source --directory TREE-PARENT --bind ADDRESS --port PORT \
  --access-log "$PRIVATE/access.jsonl"
```

In another shell, create a fresh blank test disk and hash it, boot with enough RAM to meet the
manifest profile, and stop with Ctrl-a x after the text installer shows the intended source and disk
but before beginning the installation. The launcher refuses a disk that is not blank, and the menu
boots a disk that holds an installed GRUB instead of the launcher:

```sh
qemu-img create -f qcow2 DISK.qcow2 8G
sha256sum DISK.qcow2 | cut -d' ' -f1 > "$PRIVATE/disk-before.sha256"
set -o pipefail
scripts/iso_chain.py smoke --iso "$PRIVATE/launcher.iso" --disk DISK.qcow2 \
  --config MANIFEST --capture-prefix "$PRIVATE/boot" --adapter-state matched \
  --memory-mib MIB 2>&1 | \
  tee "$PRIVATE/console.log"
sha256sum DISK.qcow2 | cut -d' ' -f1 > "$PRIVATE/disk-after.sha256"
scripts/iso_chain.py verify-launcher-log "$PRIVATE/console.log" --config MANIFEST \
  --expected-profile PROFILE
tcpdump -r "$PRIVATE/boot-net0.pcap" -w "$PRIVATE/forbidden.pcap" \
  'ip6 or (udp and (port 67 or port 68))'
scripts/iso_chain.py verify-pcap "$PRIVATE/forbidden.pcap"
```

QEMU uses pSeries/POWER9, two CPUs, a disposable snapshot overlay for disk writes, and only the
requested virtio adapters. Each netdev has a separate capture. `missing` uses a different MAC;
`duplicate` creates two adapters with the configured MAC and a second capture. Use fresh private
paths for every run. The profile's memory threshold is necessary but may not be sufficient when
`/run` is a RAM-backed filesystem; the launcher separately checks available memory and staging
space before downloading artifacts.

The GRUB menu first searches every device for a GRUB environment file, `grubenv`, in `/grub2`,
`/boot/grub2`, `/grub`, or `/boot/grub` (ADR 0018). When it finds one it adds an `installed disk`
entry that prints `ISO_CHAIN: GRUB installed-disk handoff`, loads that directory's `grub.cfg`,
and is the default; each search that finds
nothing took about 26 to 43 seconds under QEMU TCG. The menu then waits five seconds for a
selection and boots the default: the installed disk if one was found, otherwise the manifest's
default profile. Use the console arrows and Enter to select another allowed profile; name that
profile explicitly when verifying.

Before any media mount, download, or kexec, the launcher counts the non-optical disks in
`/sys/block`, which covers virtio, vSCSI, NPIV, and NVMe disks, and requires exactly one, whose
first and last MiB read as zero bytes. Otherwise it prints `disk-settle: failed`, `disk-count:
failed count=<n>`, or `disk-blank: failed`, then `disk: failed`, and stops without writing to any
disk; to reinstall, zero the disk's first and last MiB first. A disk that needs another driver is
not counted, so detach it before an install. On success it prints `disk: passed`, which
`verify-launcher-log` requires. A successful launcher then mounts the one optical device that
carries its own manifest and checks the Kickstart there by size and SHA-256. It then downloads and
checks Fedora's kernel and initrd and the pinned `.treeinfo` and `repomd.xml` from `source`, loads
the kernel with kexec, and starts Fedora Anaconda with `inst.ks=cdrom:LABEL=<volume ID>:<path>`,
static IPv4, and the manifest's repository. It does not fall back to DHCP, IPv6, another source,
another device, or another profile.

For a reviewable run, write the canonical evidence record described in the
[verification contract](docs/workflow/specs/2026-09-09-fedora-installer-profile-design.md#verification),
including SHA-256 digests of its six inputs and the four operator-reviewed observations. Then run:

```sh
scripts/iso_chain.py verify-installer-evidence --record RECORD --config MANIFEST \
  --console-log "$PRIVATE/console.log" --access-log "$PRIVATE/access.jsonl" \
  --pcap "$PRIVATE/forbidden.pcap" --disk-hash-before "$PRIVATE/disk-before.sha256" \
  --disk-hash-after "$PRIVATE/disk-after.sha256"
```

The verifier binds the manifest, console, HTTP requests, filtered network evidence, and unchanged
backing disk into one record. Operator-reviewed flags establish the record's same-run and capture
provenance and distinguish installer UI observations from machine-detected claims. Native PowerVM,
HMC/VIOS mappings, real-P9 storage, and firmware security require separate native evidence.

Ubuntu installer launcher
-------------------------

A manifest profile can instead select Ubuntu 26.04.1 LTS. The launcher downloads and checks
Ubuntu's netboot kernel and initrd, then kexecs casper with the manifest's static IPv4 settings
(`ip=...:off`, with the adapter chosen by `BOOTIF=<MAC>`) and `iso-url=` naming the live-server
ISO. casper downloads that ISO into RAM, boots its live system, and starts the subiquity installer
on the console. Nothing in the guest checks the ISO it downloads. casper's BusyBox `wget` follows
redirects and does not verify certificates, so serve it from a loopback or controlled server you
trust (ADR 0012). Subiquity's network screen then shows the adapter as static; it may still
contact the Ubuntu ports archive, NTP, and the snap store over the default route.

`ip=` carries one gateway and at most two DNS servers, so a manifest with an Ubuntu profile must
have only the default route and at most two DNS servers; any other shape fails at load.

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

`--minimum-memory-mib` is compared with the guest's `MemTotal`, which is below QEMU's `-m`. Under
QEMU pSeries POWER9, 6,144 MiB of guest RAM (`MemTotal` 6,019 MiB) is the smallest tested size that
reaches subiquity's storage screen; 4,096 MiB stops at the launcher's `/run` space check
(`docs/experiments/2026-10-02-ubuntu-installer.md`). Hence 5888.

To serve it locally, lay out a directory with hard links to the verified ISO and the two
published files:

```text
TREE/ubuntu/releases/26.04.1/release/ubuntu-26.04.1-live-server-ppc64el.iso
TREE/ubuntu/releases/26.04.1/release/netboot/ppc64el/linux
TREE/ubuntu/releases/26.04.1/release/netboot/ppc64el/initrd
```

Serve `TREE` with `serve-source`, put the profile in a manifest whose `source` is that server as the
guest sees it, and check the three pins first with a host-side copy of the manifest whose `source`
the host can reach:

```sh
scripts/iso_chain.py validate-external-source --config HOST-MANIFEST --timeout-seconds 300
```

That command allows at most 300 s per artifact, so it needs about 5.5 MB/s to fetch the 1.6 GB ISO.
Build and `smoke` as for Fedora with `--memory-mib 6144` or more. Stop at the guided storage screen,
declining any offered installer update. In the evidence record, `intended_source_confirmed` means
the operator saw subiquity's network screen show the matched adapter as `static` with the
manifest's address, and `verify-installer-evidence` reports it as
`installer-network: operator-reviewed`. The HTTP evidence must be exactly the kernel, initrd, and
ISO requests, once each. Under the snapshot overlay the disk hashes show only that the backing file
was untouched.

When the manifest also carries `ssh_authorized_keys` and `login_user`, the Ubuntu profile installs
unattended instead (ADR 0020). `build` renders cloud-init user data from the manifest and
`assets/autoinstall/ubuntu-26.04.1.json`, writes it as `/user-data` beside an empty `/meta-data` at
the ISO root, and binds its size and SHA-256 on the kernel command line. The launcher mounts the
media, refuses a second volume under the ISO's label in any case or as a FAT boot label, checks
both files, and adds `autoinstall ds=nocloud` and a `cc:` token that points cloud-init's NoCloud
datasource at the ISO's label. The user data is one JSON document after `#cloud-config`, so each
key is one quoted value. Its autoinstall configuration:

- creates the login user with no password, the manifest's keys, and no sudo rule; no `identity`
  section exists, root stays locked, and the SSH server allows no password logins;
- in `early-commands`, counts the non-optical disks as the launcher does, stops unless exactly
  one is present with zero first and last MiB, and prints `autoinstall-disk: passed <disk>`; the
  `direct` storage layout then uses that disk;
- installs offline from the live ISO's packages, with no mirror, geoip mirror choice, installer
  refresh, or snaps; the installer still reaches geoip, the snap store, and NTS time servers, and
  the installed system keeps Ubuntu's default apt sources;
- writes a netplan configuration matching the manifest MAC with its address, default route, and
  DNS servers, and no DHCP or IPv6, and sets the host name to `lpar`;
- ends with a late command that sets `iso_chain_installed=1` in the installed `grubenv`, then
  reboots. A keyed Ubuntu ISO's menu boots an installed disk only when that marker is set, so an
  install interrupted earlier stays on the installer entry, whose blank-disk guard refuses it.

`build` refuses an `lpar` ending in `-`, which is not a valid host name, and a keyed manifest that
mixes Rocky and Ubuntu profiles.

Rocky installer launcher
------------------------

A manifest profile can instead select Rocky Linux 9.8, the newest Rocky release that runs on
POWER9. A `rocky`/`9.8` profile has a Fedora profile's fields without `kickstart`, and its
`repository.path` must end in `/BaseOS/ppc64le/os`. The launcher downloads and checks the four pins
and does not mount the launcher media. It then kexecs Anaconda with Fedora's static network
arguments and `inst.repo=`, and no `inst.ks=`, so the installer starts interactive (ADR 0013).
Anaconda first offers VNC or text mode; choose text. It fetches its `install.img` runtime and adds
the sibling AppStream repository from the same mirror, neither of them pinned, as with Fedora.

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

`prepare-rocky-source` requires that digest. It requires the `.treeinfo` to name Rocky Linux 9.8
ppc64le `BaseOS`, to list the same digest for `images/boot.iso`, and to name
`../../../AppStream/ppc64le/os/` as the AppStream repository. It extracts the kernel and initrd
from the ISO, checks them against `.treeinfo`, and writes a `profile.json` that pins the mirror's
copies. It makes no network request and needs `xorriso`; on macOS run it in the build image, as
shown for `prepare-fedora-source`.

```sh
scripts/iso_chain.py prepare-rocky-source \
  --iso "$HOME/iso-build/rocky/Rocky-9.8-ppc64le-boot.iso" \
  --iso-sha256 bd0db737aeaede1817971cade75e72027dffe836ff983852ad940a6923775a70 \
  --tree "$HOME/iso-build/rocky/tree" \
  --repository-path /pub/rocky/9.8/BaseOS/ppc64le/os \
  --minimum-memory-mib 6400 --output "$HOME/iso-build/rocky-prepared"
```

The installer itself started in 4,096 MiB of guest RAM, but the launcher needs `/run` space for the
257 MB kernel and initrd plus 1 GiB. Under QEMU pSeries POWER9, 6,144 MiB stops at the launcher's
`run-space` check and 6,656 MiB (`MemTotal` 6,529 MiB) reaches Installation Destination
(`docs/experiments/2026-10-02-rocky-installer.md`). Hence 6400, the passing arm's `MemTotal`
rounded down. A guest with a `MemTotal` from 6,400 through about 6,528 MiB passes that gate but may
still stop at `run-space`, so give the guest at least 6,656 MiB.

`source` may be the Rocky mirror's origin or a local server. A local tree needs Rocky's paths
below `pub/rocky/9.8/`: BaseOS's `.treeinfo`, `images/install.img`, `ppc/ppc64/vmlinuz`,
`ppc/ppc64/initrd.img`, and `repodata/`, plus AppStream's `repodata/`. Check the four pins with
`validate-external-source`, then build and `smoke` with `--memory-mib 6656` or more. Stop at
Installation Destination; never begin the installation. Anaconda also requests
`images/updates.img` and `images/product.img`, which Rocky does not publish. The HTTP evidence
admits those two 404s for Rocky only, and otherwise allows only the four pins, then BaseOS and
AppStream paths. `verify-installer-evidence` reports `intended-source: operator-reviewed` for
Anaconda's Installation Source spoke.

When the manifest also carries `ssh_authorized_keys` and `login_user`, the Rocky profile installs
unattended instead (ADR 0019). `build` renders a Kickstart from the manifest and
`assets/kickstart/rocky-9.8-unattended.ks`, stages it as `/profiles/<profile>/ks.cfg`, and binds
its size and SHA-256 on the kernel command line, so the launcher mounts the media, checks the
Kickstart, and passes `inst.ks=cdrom:LABEL=...` beside `inst.repo=`. The Kickstart:

- creates the login user with no password and one `sshkey` line per key, each quoted with
  `shlex.quote`, and keeps root locked; the user gets no sudo rule;
- in `%pre`, counts the non-optical disks as the launcher does and stops unless exactly one is
  present with zero first and last MiB, then partitions that disk by its live name with a PReP
  partition, `/boot`, and an LVM root, and installs GRUB with `--leavebootorder` so the firmware
  boot order keeps the ISO first;
- in `%post`, replaces every NetworkManager and `ifcfg` connection with one keyfile matching the
  manifest MAC, holding its address, routes, and DNS servers with IPv6 disabled, and sets the
  host name to `lpar`;
- ends with `reboot`, so the ISO's `installed disk` entry then boots the new system.

`build` refuses a key starting with `-` and an `lpar` ending in `-`, which the Kickstart parser and
Anaconda cannot take. The installed packages come from the same unpinned BaseOS and AppStream
mirror, so a local tree also needs each repository's `Packages/` for the minimal environment.

openSUSE source preparation
---------------------------

An `opensuse`/`15.6` profile pins the Leap 15.6 `boot/ppc64le/linux` and `boot/ppc64le/initrd`.
Trust starts from the tree's signed `CHECKSUMS`. Check it with the openSUSE Project Signing Key
(`AD485664E901B867051AB15F35A2F86E29B700A4`), whose expiry is 2026-06-19; `gpgv` still exits 0 for
the expired key, so read `gpg --show-keys` for the date rather than relying on a warning. The key
file comes from the same server as `CHECKSUMS`, so the `grep` below requires the signature to be
from that fingerprint rather than from whatever key the file holds. If it prints the stop message,
do not continue, whatever `gpgv` printed:

```sh
B=https://download.opensuse.org/distribution/leap/15.6/repo/oss
mkdir -p "$HOME/iso-build/opensuse/tree/boot/ppc64le" "$HOME/iso-build/opensuse/tree/media.1"
cd "$HOME/iso-build/opensuse"
curl --fail -O "$B/CHECKSUMS" -O "$B/CHECKSUMS.asc" -O "$B/gpg-pubkey-29b700a4-62b07e22.asc"
gpg --dearmor < gpg-pubkey-29b700a4-62b07e22.asc > opensuse.gpg
if gpgv --status-fd 1 --keyring ./opensuse.gpg CHECKSUMS.asc CHECKSUMS |
  grep -q 'VALIDSIG .* AD485664E901B867051AB15F35A2F86E29B700A4$'; then
  curl --fail -o tree/media.1/products "$B/media.1/products"
  curl --fail -o tree/boot/ppc64le/linux "$B/boot/ppc64le/linux"
  curl --fail -o tree/boot/ppc64le/initrd "$B/boot/ppc64le/initrd"
else
  echo 'CHECKSUMS is not signed by the openSUSE key; stop' >&2
fi
```

`prepare-opensuse-source` needs the tree to hold `media.1/products`, `boot/ppc64le/linux`, and
`boot/ppc64le/initrd`. It requires `CHECKSUMS` to list all three, `media.1/products` to be exactly
`/ openSUSE-Leap 15.6-1`, and both boot files to match their entries. It writes a `profile.json`
that pins the mirror's copies. It runs no subprocess and makes no network request.

```sh
scripts/iso_chain.py prepare-opensuse-source \
  --checksums "$HOME/iso-build/opensuse/CHECKSUMS" \
  --tree "$HOME/iso-build/opensuse/tree" \
  --repository-path /distribution/leap/15.6/repo/oss \
  --minimum-memory-mib 6400 --output "$HOME/iso-build/opensuse-prepared"
```

As for Rocky, the launcher's `/run` gate sets the memory floor: it needs space for the 249 MB
kernel and initrd plus 1 GiB. Under QEMU pSeries POWER9, 6,144 MiB stops at `run-space` and
6,656 MiB (`MemTotal` 6,529 MiB) reaches YaST
(`docs/experiments/2026-10-02-opensuse-installer.md`). Hence 6400; give the guest at least
6,656 MiB.

A manifest with an openSUSE profile allows only the default route and at most one DNS server,
because linuxrc's `ifcfg=` carries one gateway. The launcher downloads only the two pins and
starts linuxrc with `ifcfg=<mac>=<address>,<gateway>[,<dns>]`, `hostname=`, `install=` naming
`source` plus the repository path, `textmode=1`, and `self_update=0`. linuxrc then loads the
installation system from that repository and checks each part against the digests its initrd
carries. A local tree needs, below `distribution/leap/15.6/repo/oss/`: `CHECKSUMS` and
`CHECKSUMS.asc`, `media.1/`, `repodata/`, the `gpg-pubkey-*.asc` keys, `control.xml`, and
`boot/ppc64le/`'s `linux`, `initrd`, `config`, `common`, `root`, `bind`, `control.xml`, and
`cracklib-dict-full.rpm`. Check the pins with `validate-external-source`, then build and `smoke`
with `--memory-mib 6656` or more. Answer No to the online repositories, choose a role, and stop
at Suggested Partitioning; never begin the installation. Any linuxrc digest dialog or YaST
signature warning fails the run. linuxrc reads `autoinst.xml` from `source` without a digest check
and starts AutoYaST if one is served, so serve only a trusted tree and stop at once if YaST shows
"Preparing System for Automated Installation". YaST also fetches release notes from
`doc.opensuse.org`, so the HTTP evidence covers `source` only. It admits `HEAD` requests (200
status, 0 bytes) and ten optional paths that return 404 once each, all for openSUSE only.
`verify-launcher-log` compares the installer command line whole and requires linuxrc's
`IP addresses:` line to show the manifest address.

Target-bound media for hmcpctl
------------------------------

hmcpctl builds media after it creates a partition and reads its adapter's MAC
([ADR 0015](docs/adr/0015-emit-a-target-bound-producer-result.md)). Instead of `--config`, `build`
and `container-build` take a per-partition target request and an operator base manifest:

```json
{
  "format": "iso-chain-target-v1",
  "profile": "rocky-9.8",
  "lpar": "sys-r1",
  "mac": "52:54:00:12:34:56",
  "network": {
    "address": "10.0.2.15/24",
    "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}],
    "dns": ["10.0.2.3"]
  },
  "operation_binding": "00000000000000000000000000000001"
}
```

The base manifest holds exactly `version`, `source`, and `profiles`, as prepared above. `profile`
names a distribution and release and must match exactly one base profile; the ISO carries only
that profile, under its base key, and its embedded manifest records `operation_binding`. `lpar`
is a lower-case identifier of at most 32 characters and becomes the installer hostname.

The request may also carry `ssh_authorized_keys`, 1 to 16 public keys that are each one printable
line of 1 to 8,192 characters, and `login_user`, matching `[a-z_][a-z0-9_-]{0,31}`; they appear
together or not at all, the same bounds hmcpctl applies in built mode. They become top-level fields
of the composed manifest, so its digest binds them, and they never reach the kernel command line
or the result ([ADR 0017](docs/adr/0017-carry-login-values-in-the-manifest.md)). The Rocky and
Ubuntu profiles apply them, as the unattended installs above, so `build` and `container-build`
refuse a manifest carrying them unless every profile is Rocky or every profile is Ubuntu. Requests
and manifests may be up to 2 MiB.

A bound request must be published, and only a bound request may be. The operator configures the
fixed part of the command, and only the request path varies:

```sh
umask 077
scripts/iso_chain.py container-build --kernel LAUNCHER/vmlinuz \
  --initramfs LAUNCHER/initramfs.img --profiles PREPARED --base-config BASE.json \
  --publish-dir PUBLISH-DIR --publish-url https://MEDIA-HOST/iso --target REQUEST.json
```

The ISO is linked, never replaced, as `PUBLISH-DIR/<iso_sha256>.iso`. Its mode is the building
process's: `build` follows its umask, while `container-build` gets the container's default
(world-readable with the pinned image), so control access through the publish directory itself.
The publish URL follows the `source` rules, which forbid `?` and `#` in both URLs. `build` prints
one line of canonical JSON on stdout, and child tools' output goes to stderr:

| Field | Value |
| --- | --- |
| `format` | `iso-chain-media-v1` |
| `iso_sha256`, `iso_size` | the ISO's SHA-256 and byte size |
| `manifest_sha256` | the embedded manifest's SHA-256 |
| `distribution`, `release`, `architecture` | the profile's, and `ppc64le` |
| `mac`, `network` | the request's, `network` without `mac` |
| `operation_binding`, `url` | published media only; `url` is the publish URL plus `/<iso_sha256>.iso` |

An unbound request, or `--config`, with `--output` prints the same result without the last two
fields; that is hmcpctl's prepared mode. A result names one installer, so a `--config` build
whose manifest holds several profiles prints nothing. `inspect --result ISO` prints the result for
an existing one-profile ISO and refuses a published, bound one. `smoke`, the `install-*`, and
the `verify-*` commands take the embedded manifest, which `inspect ISO` recovers. Nothing removes
published media: the operator deletes `PUBLISH-DIR/*.iso` files and any `.iso-chain-*`
directories an interrupted build left.
The build is not byte-reproducible, so every run, an identical retry included, publishes a new ISO.

Unattended installation proof
-----------------------------

`install-fedora` is separate from the non-persistent `smoke` command. It accepts no existing disk,
creates a fresh standalone qcow2 in private staging, installs from the launcher ISO, then boots that
disk without the ISO or a network adapter. Success requires both QEMU phases to exit zero, the disk
digest to change, and the installed system to emit exactly one canonical boot marker. The raw
install capture is retained through a private FIFO with an 8 GiB hard ceiling; each console log has
a 16 MiB ceiling.

Keep the HTTP server running, then use a new output path:

```sh
scripts/iso_chain.py install-fedora --iso "$PRIVATE/launcher.iso" --config MANIFEST \
  --output "$PRIVATE/install" --disk-size-gib 20 --memory-mib 32768 \
  --install-timeout-seconds 7200 --boot-timeout-seconds 600
tcpdump -r "$PRIVATE/install/install.pcap" -w "$PRIVATE/install-forbidden.pcap" \
  'ip6 or (udp and (port 67 or port 68))'
jq -r '.disk_sha256_before' "$PRIVATE/install/result.json" \
  >"$PRIVATE/disk-before.sha256"
jq -r '.disk_sha256_after' "$PRIVATE/install/result.json" \
  >"$PRIVATE/disk-after.sha256"
```

Create a canonical version-1 installation record with `version`, `manifest_sha256`, `profile`,
`qemu_memory_mib`, `disk_label`, `same_run_collection`, and `evidence_sha256`. The digest map must
bind exactly `manifest`, `kickstart`, `install_console`, `boot_console`, `access_log`, `result`,
`install_pcap`, `disk_before`, and `disk_after`. Set `same_run_collection` only after checking that
all inputs came from this run. Then verify the bound set:

```sh
scripts/iso_chain.py verify-fedora-install-evidence --record RECORD --config MANIFEST \
  --kickstart assets/kickstart/fedora-44-power9.ks \
  --install-console-log "$PRIVATE/install/install-console.log" \
  --boot-console-log "$PRIVATE/install/boot-console.log" --access-log "$PRIVATE/access.jsonl" \
  --result "$PRIVATE/install/result.json" --install-pcap "$PRIVATE/install-forbidden.pcap" \
  --disk-hash-before "$PRIVATE/disk-before.sha256" \
  --disk-hash-after "$PRIVATE/disk-after.sha256"
```

The reference Kickstart intentionally targets only Fedora Server 44 and guest disk `/dev/vda`.
The install command mutates only the fresh disk it creates. Native PowerVM, HMC/VIOS mappings,
physical POWER9 storage, and other installer or storage layouts remain separate work.
The [unattended installation experiment](docs/experiments/2026-09-10-fedora-kickstart-install.md)
records the complete command sequence, live evidence, controlled failures, and emulator boundary.

`install-rocky` takes the same arguments, with defaults of 8,192 MiB, a 14,400-second install,
and a 3,600-second boot, and requires a selected Rocky profile with login values. Both QEMU runs
attach the ISO first in the boot order, the fresh disk, and the manifest NIC, each with its own
capture, and pass `-no-reboot`. The first run ends when the Kickstart reboots; the disk digest must
have changed. The second boots that disk through the ISO's `installed disk` entry and ends when the
console shows `<lpar> login:`, when the harness stops QEMU. `result.json` records `boot_stop:
login-prompt` in place of `boot_exit_status`, and its `disk_sha256_after` is the disk as the
installer left it; the boot then writes the disk again. Filter both captures as above, then:

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
[unattended Rocky experiment](docs/experiments/2026-10-02-rocky-unattended-install.md) records a
QEMU run, including an SSH login with the injected key; it is not native PowerVM evidence.

`install-ubuntu` and `verify-ubuntu-install-evidence` take the same arguments and defaults as the
Rocky commands and require a selected Ubuntu profile with login values. Give the install
`--memory-mib 8192` or more. The verifier makes the same checks, except that the HTTP traffic
must be exactly the kernel, initrd, and live ISO requests, the launcher evidence must carry the
whole unattended casper command line, and the install console must hold one
`autoinstall-disk: passed <disk>` line after the handoff, which only a run that read the user data
prints. Its second result line is `user-data: passed`.

The [Fedora installer VM experiment](docs/experiments/2026-09-09-fedora-installer.md) reached the
Fedora 44 text installer with the intended local source, software selection, static interface, and
test disk visible. The backing disk digest stayed unchanged and the filtered capture contained no
DHCP or IPv6 packets. Native PowerVM was not run.

The earlier [static-launcher VM experiment](docs/experiments/2026-09-08-static-launcher.md) passed all five
arms: two configured defaults, a manual alternate profile, and missing/duplicate adapter failures.
It produced exactly three HTTP probes; all six captures were DHCP- and IPv6-free. Native PowerVM
was not run.

The earlier [optical/kexec experiment](docs/experiments/2026-09-08-power9-optical-bootstrap.md)
records a historical prototype; its build and smoke commands predate this manifest-based interface.
