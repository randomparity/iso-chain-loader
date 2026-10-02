ISO Chain Loader
================

A ppc64le optical launcher with a GRUB profile menu, per-system static IPv4 settings, verified
Fedora installer and Kickstart carried on the ISO itself, a pinned public Fedora repository, and
a kexec handoff to the text installer.

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

`smoke` and `install-fedora` still require ppc64le QEMU and do not run on macOS.

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
`install.img`, from the mirror. No digest checks that runtime; use a mirror you trust.

Trust starts from Fedora's signed release. Download the Fedora 44 ppc64le netinst ISO and its
`CHECKSUM` file from the release's `iso/` directory, and check the signature inside the build image,
which ships Fedora's release keys:

```sh
B=https://dl.fedoraproject.org/pub/fedora-secondary/releases/44/Everything/ppc64le
mkdir -p "$HOME/iso-build/netinst" && cd "$HOME/iso-build/netinst"
curl --fail -O "$B/iso/Fedora-Everything-netinst-ppc64le-44-1.7.iso"
curl --fail -O "$B/iso/Fedora-Everything-44-1.7-ppc64le-CHECKSUM"
docker run --rm -v "$PWD":/w:ro iso-chain-builder:44 sh -c \
  'gpg --batch --quiet --dearmor </etc/pki/rpm-gpg/RPM-GPG-KEY-fedora-44-primary >/tmp/k.gpg &&
   gpgv --keyring /tmp/k.gpg /w/Fedora-Everything-44-1.7-ppc64le-CHECKSUM &&
   cd /w && sha256sum -c --ignore-missing Fedora-Everything-44-1.7-ppc64le-CHECKSUM'
```

Take the ISO's SHA-256 from that verified file. Then copy the two metadata files of the matching
tree into a directory of their own:

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
docker run --rm --mount "type=bind,source=$R,target=$R,readonly" \
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
back to another.

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
serve it with `serve-fedora-source`, and set `source` and `repository.path` to that server. The
bundled server writes the JSONL access log that the evidence verifiers read; an ordinary external
web server's logs must be adapted to its `method`, `path`, `status`, `bytes`, and monotonic `index`
fields, a weaker evidence boundary.

```sh
scripts/iso_chain.py serve-fedora-source --directory TREE-PARENT --bind ADDRESS --port PORT \
  --access-log "$PRIVATE/access.jsonl"
```

In another shell, hash the test disk, boot with enough RAM to meet the manifest profile, and stop
with Ctrl-a x after the text installer shows the intended source and disk but before beginning the
installation:

```sh
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

The GRUB menu waits five seconds for a selection, then boots the manifest's default profile.
Use the console arrows and Enter to select another allowed profile; name that profile explicitly
when verifying. A successful launcher mounts the one optical device that carries its own
manifest, copies the kernel and initramfs from it with their exact size and SHA-256 digest checked,
fetches and checks the pinned `.treeinfo` and `repomd.xml`, loads the kernel with kexec, and starts
Fedora Anaconda with the embedded Kickstart, static IPv4, and the manifest's repository. It does
not fall back to DHCP, IPv6, another source, another device, or another profile.

For a reviewable run, write the canonical evidence record described in the
[verification contract](docs/workflow/specs/2026-09-09-fedora-installer-profile-design.md#verification),
including SHA-256 digests of its six inputs and the four operator-reviewed observations. Then run:

```sh
scripts/iso_chain.py verify-fedora-evidence --record RECORD --config MANIFEST \
  --console-log "$PRIVATE/console.log" --access-log "$PRIVATE/access.jsonl" \
  --pcap "$PRIVATE/forbidden.pcap" --disk-hash-before "$PRIVATE/disk-before.sha256" \
  --disk-hash-after "$PRIVATE/disk-after.sha256"
```

The verifier binds the manifest, console, HTTP requests, filtered network evidence, and unchanged
backing disk into one record. Operator-reviewed flags establish the record's same-run and capture
provenance and distinguish installer UI observations from machine-detected claims. Native PowerVM,
HMC/VIOS mappings, real-P9 storage, and firmware security require separate native evidence.

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
