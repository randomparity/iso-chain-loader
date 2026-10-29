# Verification and evidence

This guide runs the QEMU smoke and installation proofs and checks their evidence with the
existing verifiers. Each distribution guide names its stop point and harness differences.

## Installer smoke proof

Start in the shell that built the ISO in [Build the ISO](building-media.md#build-the-iso), which
set `umask 077` and created the private run directory with `PRIVATE=$(mktemp -d)`; the commands
below write their evidence under `$PRIVATE`.

A local QEMU run can serve the repository itself instead of a public mirror: hold a full copy of the
same Fedora tree, serve it with `serve-source`, and set `source` and `repository.path` to that
server. The bundled server writes the JSONL access log that the evidence verifiers read; an ordinary
external web server's logs must be adapted to its `method`, `path`, `status`, `bytes`, and monotonic
`index` fields, a weaker evidence boundary.

```sh
scripts/iso_chain.py serve-source --directory TREE-PARENT --bind ADDRESS --port PORT \
  --access-log "$PRIVATE/access.jsonl"
```

In another shell, with the same `umask 077` and `PRIVATE` value, create a fresh blank test disk and
hash it, boot with enough RAM to meet the manifest profile, and stop with Ctrl-a x after the text
installer shows the intended source and disk but before beginning the installation. The launcher
refuses a disk that is not blank, and the menu boots a disk that holds an installed GRUB instead of
the launcher:

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
`duplicate` creates two adapters with the configured MAC and a second capture. The profile's memory
threshold is necessary but may not be sufficient when `/run` is a RAM-backed filesystem; the
launcher separately checks available memory and staging space before downloading artifacts.

### Installed-disk menu and disk guards

The GRUB menu first searches every device for a GRUB environment file, `grubenv`, in `/grub2`,
`/boot/grub2`, `/grub`, or `/boot/grub` (ADR 0018). On btrfs it looks inside the default subvolume,
which is where openSUSE's snapper layout keeps them (ADR 0024). When it finds one it adds an
`installed disk` entry that prints `ISO_CHAIN: GRUB installed-disk handoff`, loads that directory's
`grub.cfg`, and is the default. An ISO built from a manifest with `ssh_authorized_keys` and
`login_user` adds the entry only when that `grubenv` also holds `iso_chain_installed=1`, which its
unattended install writes last (ADR 0020, ADR 0021). Any other ISO boots a disk whose install was
interrupted after its installer wrote `grubenv`; zero the disk's first and last MiB to reinstall it
(ADR 0025). Each search that finds nothing took about 26 to 43 seconds under QEMU TCG. The menu
then waits five seconds for a selection and boots the default: the installed disk if one was found,
otherwise the manifest's default profile. Use the console arrows and Enter to select another
allowed profile; name that profile explicitly when verifying.

Before any media mount, download, or kexec, the launcher counts the non-optical disks in
`/sys/block`, which covers virtio, vSCSI, NPIV, and NVMe disks, and requires exactly one, whose
first and last MiB read as zero bytes. Otherwise it prints `disk-settle: failed`, `disk-count:
failed count=<n>`, or `disk-blank: failed`, then `disk: failed`, and stops without writing to any
disk; to reinstall, zero the disk's first and last MiB first. VIOS `mklv` does not zero a newly
created logical volume: residual data can trigger `disk-blank: failed` even before its first
install. Zero the intended install target's first and last MiB before that first install too.
A disk that needs another driver is
not counted, so while a PCI mass-storage or Fibre Channel controller, or a VIO vSCSI or NPIV
adapter, has no bound driver, the launcher refuses first with `disk-controller: failed unbound=<n>`,
then `disk: failed` (ADR 0022); remove that adapter from the partition before an install. On success
it prints `disk: passed`, which `verify-launcher-log` requires. A successful launcher then mounts
the one optical device that carries its own manifest and checks the Kickstart there by size and
SHA-256. It then downloads and checks Fedora's kernel and initrd and the pinned `.treeinfo` and
`repomd.xml` from `source`, loads the kernel with kexec, and starts Fedora Anaconda with
`inst.ks=cdrom:LABEL=<volume ID>:<path>`, static IPv4, and the manifest's repository. It does not
fall back to DHCP, IPv6, another source, another device, or another profile.

### Installer evidence

For a reviewable run, write the canonical evidence record described in the
[verification contract](../workflow/specs/2026-09-09-fedora-installer-profile-design.md#verification),
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

## Unattended installation proof

`install-fedora` is separate from the non-persistent `smoke` command. It accepts no existing disk,
creates a fresh standalone qcow2 in private staging, installs from the launcher ISO, then boots that
disk without the ISO or a network adapter. Success requires both QEMU phases to exit zero, the disk
digest to change, and the installed system to emit exactly one canonical boot marker. The raw
install capture is retained through a private FIFO with an 8 GiB hard ceiling; each console log has
a 16 MiB ceiling. SIGHUP or SIGTERM stops a running install command's QEMU, removes its private
staging directory, and exits with 128 plus the signal number, unless the command started with that
signal ignored (`nohup`); a result already published stays. After SIGKILL or a crash, delete any
`.iso-chain-install-*` directory left in the output parent.

Keep the HTTP server from the [installer smoke proof](#installer-smoke-proof) running, then use a
new output path:

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

For an authenticated FTP manifest, the three installation verifiers use the same `--access-log`
option and version-1 record, but the file must be the **untouched standard xferlog**, not HTTP
JSON lines or a conversion to GET records. `evidence_sha256.access_log` hashes those raw bytes;
the digest-bound manifest source selects the format. Successful FTP verification prints
`ftp-evidence: passed`; HTTP(S) keeps `http-evidence: passed`.

Collect a fresh, private log for the run's dedicated read-only account. A vsftpd server can emit
this format with `xferlog_enable=YES`, `xferlog_std_format=YES`, and `xferlog_file` naming that fresh
log. The supported subset has 18 whitespace-separated tokens (five for the timestamp), an IPv4
client, positive transferred bytes, and `b _ o r USER ftp 0 * c`: complete binary outbound
real-user transfers with no transformation. The decoded username must match the manifest and be
printable ASCII without whitespace. An anonymous, guest, incomplete, ASCII or upload record is
refused; the [FTP install evidence design](../workflow/specs/2026-10-27-ftp-install-evidence-design.md)
defines this grammar. The server/account configuration remains the operator's responsibility.

The logged filename must be absolute **inside the account's chroot namespace**, as with
`chroot_local_user=YES`, and use the existing canonical access-log path grammar. If `source` ends
in `/pub`, a profile's `/repository/file` must appear as `/pub/repository/file` in the raw log.
Host filesystem prefixes, path rewriting and escaped filenames are unsupported. Fedora and Rocky
require the launcher's ordered pins at exact sizes, followed only by selected repository traffic
(BaseOS and AppStream for Rocky); Ubuntu requires exactly kernel, initramfs and live ISO. Missing
optional-file probes produce no successful transfer record and need no invented entries.

Review the entire same-run set before asserting `same_run_collection`: xferlog does not prove the
absence of failed control commands, independently authenticate the server, or replace the console,
process, capture and disk proofs. Keep this log, account, manifests and console/capture private.
This support covers installation verification; `verify-installer-evidence` readiness expansion
requires a separate decision. The [FTP experiment](../experiments/2026-10-27-ftp-installs-and-residue.md)
records Fedora, Rocky and Ubuntu installs, openSUSE readiness, and installed credential residue
under QEMU pSeries/POWER9; native PowerVM remains #72. Follow the
[FTP operator runbook](../ftp-operator-runbook.md) for account and media cleanup. See
[ADR 0027](../adr/0027-accept-plain-ftp-sources-with-userinfo.md).

`install-rocky`, `install-ubuntu` and their verifiers follow this harness; their differences are in
the [Rocky](rocky.md#unattended-installation) and [Ubuntu](ubuntu.md#unattended-installation)
guides.

## JSON reports for validation and verification

Add `--json` after `validate-config` or any of `verify-log`, `verify-launcher-log`, `verify-pcap`,
`verify-installer-evidence`, `verify-fedora-install-evidence`, `verify-rocky-install-evidence`
and `verify-ubuntu-install-evidence`. For example:

```sh
python scripts/iso_chain.py validate-config --config manifest.json --json
python scripts/iso_chain.py verify-log console.log --json
```

Normal completion writes one compact, sorted UTF-8 JSON object and newline to stdout, with
empty stderr. These synthetic reports illustrate success and validation failure:

```json
{"checks":["configuration","renderability"],"command":"validate-config","error":null,"outcome":"passed","version":"iso-chain-report-v1"}
{"checks":[],"command":"verify-log","error":{"category":"validation","field":null},"outcome":"failed","version":"iso-chain-report-v1"}
```

`command` identifies the check's contract; `outcome` is `passed` or `failed`. Successful offline
validation completes `configuration` and `renderability`; each successful verifier completes
`verification`, meaning its existing whole-command checks, including operator-reviewed assertions.
Failures report no completed atomic checks (`[]`), even when internal prerequisites completed.
The report does not strengthen evidence or prove the offline command's explicitly untested properties.

`error` is null on success, otherwise `{ "category": ..., "field": ... }`. Categories are
`usage`, `validation`, `external-tool` and `io`; `field` is a known static schema path or null.
Reports omit error prose, input values, paths and tool output. Success exits 0; usage/validation
exit 2; tcpdump launch/failure/timeout retains exit 2 with `external-tool`; uncaught filesystem
errors exit 1 (`io`); uncaught child failures preserve their exit code (`external-tool`).

`--help` remains human help on stdout with exit 0, including with `--json`. Parse errors use JSON
only when the first argument is an exact supported command and standalone `--json` precedes `--`.
Other commands keep their existing interfaces. Default text, canonical evidence files,
`iso-chain-media-v1`, `inspect --result` and `validate-external-source` remain unchanged.
Consumers must recognize `iso-chain-report-v1`; see [ADR 0030](../adr/0030-report-validation-as-json.md).

## Privacy and proof limits

Keep manifests, media, source trees, console logs, access logs, disk hashes and packet captures in
private storage (`umask 077`), using fresh output paths for every run, because they can contain
machine or network identifiers. Local checks and CI do not build or boot media. Emulator results
establish only their recorded QEMU boundary; native PowerVM requires separate proof.
