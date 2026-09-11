ISO Chain Loader
================

A ppc64le optical launcher with a GRUB profile menu, per-system static IPv4 settings, verified
Fedora installer downloads, and a kexec handoff to the text installer.

Development
-----------

Development is supported on an x86_64 Linux host with Python 3.14 and just
1.57 or newer. Set up the isolated Python environment and install the Git hook:

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
[version 2 manifest](docs/workflow/specs/2026-09-09-fedora-installer-profile-design.md#manifest-version-2).
The source tree and every output path must not already exist.

```sh
scripts/iso_chain.py prepare-fedora-source --iso Fedora-Server-dvd-ppc64le-44-1.7.iso \
  --iso-sha256 d0d11c768e2933a421e81db2606eafd512f9d75a15e0d591277837d2c97c908b \
  --minimum-memory-mib MIB --output SOURCE
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
and SHA-256 digest, loads them with kexec, and starts Fedora Anaconda with static IPv4 and the local
repository. It does not fall back to DHCP, IPv6, a public mirror, or another profile.

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
backing disk into one run. Operator-reviewed flags distinguish installer UI observations from
machine-detected claims. Native PowerVM, HMC/VIOS mappings, real-P9 storage, and firmware security
require separate native evidence.

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
