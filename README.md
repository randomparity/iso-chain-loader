ISO Chain Loader
================

A ppc64le optical launcher with a GRUB profile menu, per-system static IPv4 settings, and one
bounded HTTP reachability probe. Installer downloads and the kexec handoff are not implemented
by the static launcher.

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

Static launcher
---------------

Prepare the reusable payload inside a disposable ppc64le Linux environment with Python 3.14,
dracut, systemd, iproute, curl, and the matching kernel modules installed. Copy this checkout's
`scripts/` and `assets/dracut/` together so preparation uses the local launcher assets:

```sh
sudo python3 scripts/iso_chain.py prepare-initramfs --kernel-version VERSION --output FILE
```

On the build host, supply that payload, its matching ppc64le kernel, `powerpc-ieee1275` GRUB
modules, and a private manifest following the
[version 1 schema](docs/workflow/specs/2026-09-08-per-lpar-static-launcher-design.md#manifest-contract).
`build` validates and embeds the manifest; `inspect` returns its canonical JSON. Outputs must not
already exist. Keep manifests, media, console logs, and packet captures in private storage.

```sh
umask 077
PRIVATE=$(mktemp -d)
scripts/iso_chain.py build --grub-modules DIR --kernel FILE --initramfs FILE \
  --config MANIFEST --output "$PRIVATE/launcher.iso"
scripts/iso_chain.py inspect "$PRIVATE/launcher.iso" > "$PRIVATE/embedded.json"
set -o pipefail
scripts/iso_chain.py smoke --iso "$PRIVATE/launcher.iso" --disk DISK.qcow2 \
  --config MANIFEST --capture-prefix "$PRIVATE/boot" --adapter-state matched 2>&1 | \
  tee "$PRIVATE/console.log"
scripts/iso_chain.py verify-launcher-log "$PRIVATE/console.log" --config MANIFEST \
  --expected-profile PROFILE
scripts/iso_chain.py verify-pcap "$PRIVATE/boot-net0.pcap"
```

QEMU uses pSeries/POWER9, 4 GiB RAM, two CPUs, snapshot disk writes, and only the requested virtio
adapters. Each netdev has a separate capture. `missing` uses a different MAC; `duplicate` creates
two adapters with the configured MAC and a second `boot-net1.pcap`. Use a fresh private capture
prefix for every run. The HTTP source must return status 200 or 206 with at most one byte.

The GRUB menu waits five seconds for a selection, then boots the manifest's default profile.
Use the console arrows and Enter to select another allowed profile; name that profile explicitly
when verifying. A successful launcher remains at its terminal target. After observing the target
and collecting a stable console interval, exit QEMU with Ctrl-a x before checking captures.

The evidence verifier requires the expected configuration digest and profile, one ordered set of
launcher pass markers, and the explicit terminal target, with no failure evidence. Packet checks
use bounded, captured `tcpdump` output and print only `dhcp-ipv6: absent` on success.
Native PowerVM, HMC/VIOS mappings, and firmware security require separate native evidence.

The [static-launcher VM experiment](docs/experiments/2026-09-08-static-launcher.md) passed all five
arms: two configured defaults, a manual alternate profile, and missing/duplicate adapter failures.
It produced exactly three HTTP probes; all six captures were DHCP- and IPv6-free. Native PowerVM
was not run.

The earlier [optical/kexec experiment](docs/experiments/2026-09-08-power9-optical-bootstrap.md)
records a historical prototype; its build and smoke commands predate this manifest-based interface.
