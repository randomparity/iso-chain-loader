ISO Chain Loader
================

A ppc64le optical launcher with a GRUB profile menu, per-system static IPv4 settings, verified
Fedora installer and Kickstart downloads, and a kexec handoff to the text installer.

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
Fedora image instead. Build the image once, then build the ISO:

```sh
just build-image
.venv/bin/python scripts/iso_chain.py container-build --config MANIFEST \
  --kernel FILE --initramfs FILE --output launcher.iso
```

`container-build` mounts the repository tree read-only and each path argument at
its own absolute path inside the container, so Docker's file sharing must reach
the manifest, the kernel, the initramfs, and the output directory. A mount source
containing a comma is rejected before any container starts. The image carries the
packaged `powerpc-ieee1275` GRUB modules, so `--grub-modules` is optional and
defaults to the image's module directory; pass it to use a different module set.

Inspect an ISO inside the same image. Its directory must be mounted writable,
because `inspect` extracts the embedded manifest into a temporary directory
beside the ISO:

```sh
docker run --rm \
  --mount type=bind,source=REPO,target=REPO,readonly \
  --mount type=bind,source=ISO-DIR,target=ISO-DIR \
  iso-chain-builder:44 python3 REPO/scripts/iso_chain.py inspect ISO-DIR/launcher.iso
```

`prepare-initramfs` still requires a ppc64le host with dracut, and `smoke` and
`install-fedora` still require ppc64le QEMU; none of the three runs on macOS.

Fedora installer launcher
-------------------------

Prepare the reusable payload inside a disposable ppc64le Linux environment with Python 3.14,
dracut, systemd, iproute, curl, and the matching kernel modules installed. Copy this checkout's
`scripts/` and `assets/dracut/` together so preparation uses the local launcher assets:

```sh
sudo python3 scripts/iso_chain.py prepare-initramfs --kernel-version VERSION --output FILE
```

Prepare a local Fedora Server 44 ppc64le source tree from a trusted DVD digest. The command verifies
the ISO before extraction and emits `profile.json`; copy that exact profile value into a private
[version 3 manifest](docs/workflow/specs/2026-09-10-fedora-kickstart-install-design.md#manifest-version-3).
The source tree and every output path must not already exist.

```sh
scripts/iso_chain.py prepare-fedora-source --iso Fedora-Server-dvd-ppc64le-44-1.7.iso \
  --iso-sha256 d0d11c768e2933a421e81db2606eafd512f9d75a15e0d591277837d2c97c908b \
  --minimum-memory-mib MIB --kickstart assets/kickstart/fedora-44-power9.ks --output SOURCE
```

On the build host, supply the reusable launcher payload, its matching ppc64le kernel,
`powerpc-ieee1275` GRUB modules, and the completed manifest. `build` validates and embeds the
manifest; `inspect` returns its canonical JSON. Keep manifests, media, source trees, console logs,
access logs, disk hashes, and packet captures in private storage because they can contain machine
or network identifiers.

```sh
umask 077
PRIVATE=$(mktemp -d)
scripts/iso_chain.py build --grub-modules DIR --kernel FILE --initramfs FILE \
  --config MANIFEST --output "$PRIVATE/launcher.iso"
scripts/iso_chain.py inspect "$PRIVATE/launcher.iso" > "$PRIVATE/embedded.json"
scripts/iso_chain.py serve-fedora-source --directory SOURCE --bind ADDRESS --port PORT \
  --access-log "$PRIVATE/access.jsonl"
```

External repository recipe
--------------------------

For a public Fedora or Red Hat mirror, use an HTTPS origin. HTTP is retained for
loopback and other controlled test servers only. Prepare or identify a tree
whose paths match the selected profile's manifest metadata: the kernel,
initramfs, Kickstart, `.treeinfo`, and `repodata/repomd.xml`. Keep the artifact
sizes and SHA-256 values from the same trusted release metadata, then set the
manifest `source` to a canonical origin such as
`https://<PUBLIC-MIRROR>/fedora/44/ppc64le` (the placeholder is not a default
or fallback).

Before booting, check the origin without modifying it:

```sh
scripts/iso_chain.py validate-external-source --config MANIFEST \
  --profile PROFILE --timeout-seconds 30
```

The command requests the five declared launcher artifacts, requires HTTP 200,
the exact streamed byte count, and the manifest's SHA-256 (it works with either
`Content-Length` or chunked responses). HTTPS uses the
system certificate and hostname checks; redirects, credentials, queries, and
fragments are rejected. The guest must have a route and DNS entry that reach
the origin, and any firewall or proxy must preserve those requests. The
launcher does not fall back to another source.

An ordinary external web server will not emit this project's JSONL access-log
records. Its logs can be adapted to the verifier's `method`, `path`, `status`,
`bytes`, and monotonic `index` fields for runtime corroboration, but that is a
weaker evidence boundary than the bundled server's deterministic log. Keep the
local-server recipe for reproducible evidence. An external mirror check is
opt-in: set `ISO_CHAIN_EXTERNAL_MIRROR` and
`ISO_CHAIN_EXTERNAL_MANIFEST` only when a specific mirror is approved and
reachable; there is no implicit URL or fallback mirror.

Fedora 44 ppc64le public mirror
--------------------------------

Fedora's primary release tree does not publish ppc64le. The Fedora mirror list
points ppc64le clients at the secondary tree, whose HTTPS base is:

```text
https://dl.fedoraproject.org/pub/fedora-secondary/releases/44/Everything/ppc64le/os
```

Use that exact base (or another HTTPS mirror selected from the
[Fedora 44 ppc64le mirror list](https://mirrors.fedoraproject.org/mirrorlist?repo=fedora-44&arch=ppc64le)) and map the manifest artifacts to the published tree:

```text
kernel:    /ppc/ppc64/vmlinuz
initramfs: /ppc/ppc64/initrd.img
treeinfo:  /.treeinfo
repomd:    /repodata/repomd.xml
```

The `.treeinfo` checksum section is the source of truth for the kernel and
initramfs sizes and digests; fetch `repodata/repomd.xml` and hash it when
constructing the manifest. The public tree does not contain this project's
Kickstart file, so a complete installation profile must provide an approved
Kickstart at the same HTTPS origin. Do not substitute `media.repo` for a
Kickstart in an installation manifest; it is suitable only as a small fifth
artifact when exercising the read-only mirror preflight itself.

From the ppc64le VM, run the preflight against the completed manifest:

```sh
scripts/iso_chain.py validate-external-source \
  --config fedora-44-ppc64le.json --profile fedora --timeout-seconds 300
```

A successful run reports all five paths with their streamed byte counts and
SHA-256 values. It proves mirror reachability and artifact integrity; it does
not replace the later installer and access-log evidence checks.

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
when verifying. A successful launcher downloads the declared artifacts, verifies their exact size
and SHA-256 digest, loads them with kexec, and starts Fedora Anaconda with the authenticated
embedded Kickstart, static IPv4, and the local repository. It does not fall back to DHCP, IPv6, a
public mirror, or another profile.

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
