# Fedora Kickstart Installation Design

Issue: [#17](https://github.com/randomparity/iso-chain-loader/issues/17)

Decision: [ADR 0006](../../adr/0006-bind-unattended-installation-in-manifest-v3.md)

## Problem

The Fedora launcher authenticates its executable installer bundle and reaches Anaconda over static
IPv4, but manifest version 2 cannot identify a Kickstart file. The existing QEMU proof deliberately
uses a snapshot disk and stops before installation. It therefore proves neither unattended
installation nor that installed ppc64le bytes boot without the launcher ISO.

## Scope and architecture

The change keeps the Python 3.14 standard-library CLI and dracut shell launcher as the only
executable repository components. It replaces the pre-release manifest with version 3, adds one
authenticated Kickstart artifact, adds a Fedora-44-specific reference Kickstart, and adds a
two-process QEMU workflow plus a separate evidence verifier. The existing `smoke` command remains
the non-persistent interactive path.

The host architecture is x86_64. Generated media, installer runtime, installed system, and live
evidence target ppc64le. QEMU uses `pseries,accel=tcg`, `power9`, two CPUs, `hvc0`, virtio network,
and virtio storage. A real ppc64le host may execute the same guest contract, but no native PowerVM
claim is made.

### Manifest version 3

Version 2 is rejected. Each profile retains its version-2 fields and adds exactly:

```json
"kickstart": {
  "path": "/profiles/fedora-44/ks.cfg",
  "size": 1234,
  "sha256": "64 lower-case hexadecimal characters"
}
```

The path uses the existing canonical absolute URL-path grammar. Size is an integer from 1 through
1,048,576 bytes. The digest uses the existing SHA-256 grammar. Canonical JSON, selected-profile
validation, and the 64 KiB manifest bound remain unchanged. Canonical output orders keys through
the existing JSON serializer.

The GRUB-generated launcher command line adds `iso_chain.profile_kickstart_path`,
`iso_chain.profile_kickstart_size`, and `iso_chain.profile_kickstart_sha256`. The complete encoded
command line, including its terminating byte, remains limited to 2,048 bytes before GRUB runs.

### Source preparation and HTTP publication

`prepare-fedora-source` adds required `--kickstart FILE`. It opens that path as a non-symlink
regular file, reads at most 1 MiB plus one byte, rejects empty or oversized input, and copies the
accepted bytes into the private source-preparation tree at `/profiles/fedora-44/ks.cfg`. It also
adds those exact bytes to the augmented installer initramfs at `/iso-chain/ks.cfg`, whose complete
digest remains authenticated by the existing initramfs artifact. It derives Kickstart size and
digest from the private standalone copy. `profile.json` contains the exact value accepted by the
version-3 profile parser.

The existing no-replace directory publication remains the only publication edge. Failure before
that edge leaves no output directory. The existing HTTP server serves the Kickstart through its
regular-file, no-symlink boundary and records its request without headers or client identity.

### Launcher handoff

The dracut launcher parses the three required Kickstart arguments with the existing exact-key,
duplicate-rejecting command-line parser. Before network traffic it validates path grammar, size,
digest, and the existing memory/space bounds. After the four version-2 downloads it downloads the
Kickstart with curl configuration disabled, IPv4 only, no redirects, a 30-second connect timeout,
a 20-minute total timeout, and the declared 1 MiB ceiling. It requires the declared exact size and
SHA-256 before reporting `artifacts: passed`.

The Anaconda arguments add `inst.ks=file:/iso-chain/ks.cfg`; Anaconda documents this form for a file
already present in the initrd. Existing `inst.repo`, static `ip`,
`ifname`, route, DNS, console, no-DHCP, and IPv6-disabled arguments remain byte-for-byte governed by
their version-2 rules. The new argument is an argv element, not shell text. A Kickstart failure uses
the existing stage-failure and kexec cleanup paths.

### Reference Kickstart

`assets/kickstart/fedora-44-power9.ks` is an executable fixture for the documented proof, not a
general storage template. It selects text mode, accepts the Fedora license, locks the root account,
disables first boot, uses UTC and the US keyboard, installs the minimal environment from the
already-selected local repository, and powers off after `%post`.

Storage commands name only `vda`: ignore other disks, initialize and clear `vda`, create the
required Power platform boot partition plus automatic system partitions, and install the
bootloader with `console=hvc0`. The fixture contains no password, SSH key, network endpoint, or
machine identifier.

An error-stopping `%post` creates `/var/lib/iso-chain/install-complete` and a root-owned executable
oneshot. The enabled service runs after `multi-user.target`, refuses to emit success without the
completion file, reads the current kernel boot ID, writes exactly
`installed-boot: passed boot_id=<canonical UUID>` to `/dev/hvc0`, and requests poweroff. A failure
to create or enable those files makes installation fail.

### Persistent QEMU workflow

`install-fedora` has required path arguments for launcher ISO, qcow2 backing disk, canonical
manifest, and one nonexistent output directory. It also accepts bounded memory, installation
timeout, and boot timeout values. The command privately stages fixed `disk.qcow2`,
`install-console.log`, `boot-console.log`, `install.pcap`, and `result.json` children and publishes
the directory once with the existing no-replace primitive. The parent filesystem must be private,
quota-limited for this run, and have at least 16 GiB free before creation.

Before creating output, the command validates the named inputs and verifies through a 60-second
`qemu-img info --output=json` call that the backing input is qcow2. It records the backing file
digest, then creates the output through the following fixed argv under a separate 60-second
timeout:

```text
qemu-img create -f qcow2 -F qcow2 -b <absolute backing> <private temporary overlay>
```

The install phase attaches the overlay writable and the launcher ISO read-only and boot-first. It
has one matched virtio adapter with the QEMU backend's IPv6 support disabled and one `filter-dump`
output. The boot phase attaches the same overlay writable without CD-ROM or network adapter. A
bounded reader streams QEMU stdout and stderr to that phase's mode-0600 console log, terminates the
process if output exceeds 16 MiB, and waits for termination. Each phase uses `subprocess.Popen`
with its declared timeout, fixed argv, no shell, and no monitor or QMP endpoint.

QEMU filter-dump has no total-byte option. The raw install capture is therefore bounded by the
phase timeout and the operator-provisioned private filesystem quota, not by this process. The 16 GiB
free-space preflight reduces ordinary exhaustion risk but is not claimed as a hard byte ceiling. A
quota or capacity failure aborts the run without publishing its directory. The operator filters the
raw capture for DHCP or IPv6 packets before constructing review evidence.

The installation phase succeeds only when QEMU exits zero before its timeout. The disk-only phase
succeeds only when QEMU exits zero before its timeout and the boot console contains exactly one
valid installed-boot marker. After both phases, the command requires the backing digest to equal
its initial digest and the overlay digest to differ from its digest immediately after creation. It
writes canonical `result.json` with exact version, zero install/boot exit statuses, configured
timeouts, and the pre/post disk digests. Only then does no-replace publication expose the run
directory. Failure removes private temporary outputs and never replaces the caller path.

### Installation evidence contract

`verify-fedora-install-evidence` consumes regular bounded files for a canonical version-1 record,
canonical manifest, exact Kickstart, install and boot logs, HTTP access log, canonical process
result, one filtered install packet capture, two backing-disk hash files, and two overlay hash files.
Logs are limited to 16 MiB, the filtered capture to 64 MiB, hash files to 65 bytes, Kickstart to 1
MiB, and the record, result, and manifest to
64 KiB.

The record contains exactly: `version`, `manifest_sha256`, `profile`, `qemu_memory_mib`,
`disk_label`, `evidence_sha256`, and `same_run_collection`. `evidence_sha256` has exactly the input
names `manifest`, `kickstart`, `install_console`, `boot_console`, `access_log`, `result`,
`install_pcap`, `backing_before`, `backing_after`, `overlay_before`, and `overlay_after`.

The verifier requires:

1. canonical record and manifest bytes and exact digest-map matches;
2. the Kickstart bytes to match the selected profile's size and digest;
3. HTTP order to begin with kernel, initramfs, treeinfo, repomd, and Kickstart, with exactly one
   successful Kickstart request and later selected-repository traffic;
4. install console launcher evidence for the selected profile and exact zero install/boot statuses
   in the bound process result;
5. exactly one canonical installed-boot marker in the separate disk-only console log;
6. equal backing hashes, unequal overlay hashes, and a nonempty final overlay;
7. the supplied filtered install capture to pass the existing DHCP/IPv6 absence check; and
8. `same_run_collection` to be true and all listed inputs to match the record.

It reports machine-detected manifest, Kickstart, HTTP, install, disk-mutation, disk-only-boot, and
network results. It labels only same-run collection as operator-reviewed. It prints no input bytes,
paths, network values, disk label, boot ID, or digests.

## Success

- Version-3 parsing, preparation, ISO construction, launcher execution, and evidence verification
  reject missing, duplicate, unknown, noncanonical, empty, oversized, replaced, or digest-mismatched
  Kickstart inputs within their named boundaries.
- The launcher requests the five declared artifacts in order and supplies one verified local
  `inst.ks` URL without changing the existing static-IPv4, local-repository, no-DHCP, or no-IPv6
  contract.
- The documented QEMU proof writes only its fresh overlay among the named disk inputs, finishes both
  phases within their declared timeouts, and observes one disk-only boot marker backed by the
  installed completion file.
- The installation verifier binds the eleven named evidence inputs and the manifest profile into
  one reviewable record and rejects replacement, false marker, unchanged overlay, changed
  backing disk, or forbidden-network evidence.
- Repository unit, shell, and guardrail checks pass on x86_64; a ppc64le QEMU live run either passes
  the complete contract or records the exact environmental prerequisite that prevented it.

## Validation

Python tests cover strict manifest version replacement, Kickstart bounds/digest/canonicalization,
source preparation publication, full-install argv and output safety, qemu-img and phase timeouts,
console overflow, disk hash invariants, result/evidence record grammar, digest binding, HTTP
ordering, marker parsing, and false positives. Controlled faults must make each new behavior test
fail before implementation.

Shell tests cover launcher parsing, fifth-artifact request/digest/size failures, `inst.ks` argv,
unchanged network arguments, kexec cleanup, and command-line overflow. A mocked curl initially
cannot serve the Kickstart so the happy-path test fails before launcher implementation.

`just check` and `.venv/bin/pre-commit run --all-files` are the local guardrails. The documented live
run uses Fedora Server 44 ppc64le, pSeries/POWER9 emulation, a fresh private evidence directory, an
explicitly disposable qcow2 overlay, bounded timeouts, and no native resource.

## Failure model

- **Actors and deployments:** a trusted local operator prepares Fedora media and supplies a reviewed
  Kickstart; the Python workflow runs on x86_64 Linux; the launcher, installer, and installed guest
  run under ppc64le pSeries/POWER9 QEMU; the local HTTP peer and all file inputs are untrusted until
  their named checks pass.
- **Invariants and assets at stake:** manifest and evidence formats remain exact; executable and
  automation bytes cross runtime boundaries only after size/digest verification; the backing image
  is immutable; writes target the new overlay's guest `/dev/vda`; bounded processes terminate; raw
  evidence and private identifiers are not published.
- **Accepted failure classes:** local HTTP denial of service is accepted within byte and time bounds;
  QEMU or Anaconda failure is accepted as a time-bounded failed run with no published output; raw
  filter-dump growth is accepted up to the operator-provisioned private filesystem quota because
  QEMU exposes no total-byte limit; malicious
  instructions deliberately placed in the reviewed Kickstart by the trusted operator are outside
  content-policy validation; native and non-Fedora behavior is outside the named deployment.
- **Covered elsewhere:** Fedora validates package signatures; existing manifest/network parsing owns
  route and source-origin grammar; QEMU owns qcow2 copy-on-write implementation; native PowerVM,
  HMC, VIOS, and physical storage safety remain separate future work.

## Threat model

- **Boundary inventory:** added boundaries are Kickstart file ingestion, manifest Kickstart fields,
  launcher Kickstart download, qcow2 overlay creation, two QEMU result streams, installed-boot
  marker parsing, and installation-evidence parsing. Widened boundaries are canonical manifests,
  GRUB command generation, local HTTP serving, kexec argv, external-tool execution, and evidence
  digest maps.
- **Actor model:** the operator is trusted to choose the Fedora ISO digest, Kickstart semantics,
  manifest, and disposable backing disk. The pre-verification ISO, Kickstart filesystem object,
  manifest/evidence syntax, HTTP peer, network bytes, QEMU output, and evidence inputs are untrusted.
- **Controls per boundary:** regular-file/no-symlink checks, exact schemas, canonical paths, byte and
  integer bounds, SHA-256, private temporary storage, no-replace publication, fixed argv, explicit
  qcow2 formats, disabled QEMU monitor, external-process timeouts, bounded console streaming,
  install-only networking and capture, disk
  digests, ordered markers, and fixed non-echoing errors govern the named boundaries.
- **Explicitly out of scope:** semantic auditing of operator-approved Kickstart content, compromise
  of trusted host tools or Fedora signing keys, denial of service inside declared bounds, native
  firmware and VIOS behavior, other Fedora releases, and other disk device names are accepted or
  owned by the failure-model entries above.
