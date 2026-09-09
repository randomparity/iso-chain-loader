ISO Chain Loader
================

A bootable ISO image for ppc64le systems that mimics network boot
functionality, allowing the user to select and install a Linux distribution
over the network.

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

POWER9 optical experiment
-------------------------

`scripts/iso_chain.py` builds a `powerpc-ieee1275` GRUB ISO, runs it in a fixed QEMU pSeries/POWER9
configuration with `-nic none` and snapshot disk writes, and verifies a private console transcript:

```sh
scripts/iso_chain.py build --grub-modules DIR --kernel FILE --initramfs FILE \
  --kernel-args 'ro root=/dev/ROOT_DEVICE rootflags=subvol=root' --output experiment.iso
set -o pipefail
scripts/iso_chain.py smoke --iso experiment.iso --disk DISK.qcow2 2>&1 | tee console.log
scripts/iso_chain.py verify-log console.log
```

The full artifact preflight, guest evidence commands, result, and native-hardware boundary are in
[the POWER9 optical-bootstrap experiment](docs/experiments/2026-09-08-power9-optical-bootstrap.md).
