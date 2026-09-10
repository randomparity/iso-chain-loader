# Fedora Installer Profile Design

Issue: [#5](https://github.com/randomparity/iso-chain-loader/issues/5)

Decision: [ADR 0005](../../adr/0005-use-a-verified-fedora-initramfs-bundle.md)

## Outcome and evidence boundary

Replace the pre-release version 1 launcher manifest with version 2 and implement one `fedora`
profile for Fedora Server 44 ppc64le compose 1.7. A prepared local HTTP tree supplies an
authenticated kernel and augmented installer initramfs plus the extracted DVD repository. The
launcher verifies executable bytes, hands static IPv4 state to Anaconda, and executes kexec.

Success is a usable interactive installer with the expected virtio storage visible, local-HTTP
source access, fixed console markers, and no partition write. The operator-supplied pSeries
POWER9-mode VM is the target-sensitive evidence environment. Native PowerVM optical behavior,
firmware/security policy, VIOS mappings, and real-P9 storage remain explicitly unproven.

## Manifest version 2

Version 1 is removed because no compatibility contract exists. The existing `lpar`, `network`,
`profiles`, and `selected_profile` concepts remain, but `profiles` becomes a non-empty object keyed
by the same lowercase identifier grammar. Each value has exactly these fields:

```json
{
  "distribution": "fedora",
  "release": "44",
  "kernel": {"path": "/profiles/fedora-44/vmlinuz", "size": 123, "sha256": "..."},
  "initramfs": {"path": "/profiles/fedora-44/initramfs.img", "size": 456, "sha256": "..."},
  "repository": {
    "path": "/repository",
    "treeinfo": {"size": 789, "sha256": "..."},
    "repomd": {"size": 321, "sha256": "..."}
  },
  "minimum_memory_mib": 4096
}
```

Artifact and repository paths are absolute URL paths made from non-empty unreserved segments, with
no dot segments, percent encoding, duplicate slash, query, or fragment. Metadata paths are derived
rather than configurable: `<repository.path>/.treeinfo` and
`<repository.path>/repodata/repomd.xml`. Executable sizes are integers from 1 through 2 GiB;
metadata sizes are 1 through 1 MiB. Digests are exactly 64 lowercase hexadecimal characters. The
only accepted distribution/release pair is `fedora`/`44`. `minimum_memory_mib` is a conservative
integer threshold from 1 through 65536 MiB compared with guest-observed `MemTotal` rounded down to
MiB. `selected_profile` must name a profile. The top-level HTTP `source` is an origin only: scheme,
canonical host, optional canonical port, and no path, query, fragment, credentials, or trailing
slash. Canonical JSON and its digest remain the immutable embedded contract.

The builder emits only the chosen profile's bounded values as `iso_chain.*` arguments and enforces
the existing 2,048-byte PowerPC command-line bound before invoking GRUB. It does not expose another
profile when a selected entry is invalid.

## Verified Fedora source preparation

`prepare-fedora-source --iso FILE --iso-sha256 DIGEST --minimum-memory-mib MIB --output DIRECTORY`
accepts a regular Fedora Server 44 ppc64le DVD ISO, a trusted caller-supplied digest and measured
minimum memory, and a nonexistent output. It verifies the ISO before extraction, reads bounded
`.treeinfo`, requires compose identity, architecture, kernel, initramfs, and runtime paths, and
extracts with fixed `xorriso` arguments into a private temporary sibling directory.

Preparation copies the repository tree, creates `/profiles/fedora-44/vmlinuz`, and builds the
augmented `/profiles/fedora-44/initramfs.img`. Fedora 44's installer initramfs is an xz-compressed
`newc` archive. The augmentation appends a second xz-compressed `newc` archive containing the
`/iso-chain` directory, `/iso-chain/install.img`, and an executable initqueue-settled hook. The hook
sources Fedora's existing `/usr/lib/anaconda-lib.sh`, requires the embedded runtime to be a regular
file, calls `anaconda_mount_sysroot` exactly once, and fails into the initramfs emergency shell if
neither Fedora's flattened `/run/rootfsbase` nor its nested `/dev/mapper/live-rw` appears. Kexec
supplies `root=/dev/mapper/live-rw`, so Fedora's normal
repository parser does not fetch stage2; Anaconda user space still consumes `inst.repo` for
packages. It writes canonical `profile.json` bytes that are exactly one `InstallerProfile` value
accepted under `profiles.<name>` by manifest version 2; the operator copies that value into a
manifest without translating security-sensitive fields. The source-ISO digest remains preparation
and experiment provenance rather than an extra manifest field. Linux
`renameat2(RENAME_NOREPLACE)`, called through the standard library's `ctypes`, publishes the
completed directory; an unavailable syscall is an actionable unsupported-platform failure. Any
wrong digest, malformed metadata, missing tool/file, oversized input, unsupported compression, or
output race fails without publishing or replacing the raced destination.

The Fedora download page and its signed checksum identify Server 44 compose 1.7 for ppc64le. The
DVD ISO is 3,013,869,568 bytes with SHA-256
`d0d11c768e2933a421e81db2606eafd512f9d75a15e0d591277837d2c97c908b`. That digest is evidence for
the selected release, not a value silently substituted for caller input.

## Launcher and handoff

The ppc64le payload additionally installs `sha256sum`, `kexec`, `mktemp`, `stat`, and `sync` from
the guest platform. After existing configuration, adapter, route, resolver, and HTTP checks pass,
the launcher:

1. reads `MemTotal`, `MemAvailable`, and `/run` filesystem availability before artifact traffic;
   it rounds the first two down to MiB, requires `MemTotal` at or above the conservative profile
   threshold, and requires both available memory and `/run` space to exceed the declared executable
   bytes by 1 GiB of kexec/installer headroom;
2. creates a mode-0700 workspace under `/run` and refuses symlinked or non-regular destinations;
3. replaces the version-1 one-byte reachability probe with downloads of the kernel, initramfs,
   derived `.treeinfo`, and derived `repodata/repomd.xml` paths; each download uses curl with
   configuration disabled, IPv4 only, no redirects, a 30-second connection timeout, a 20-minute
   total timeout, and its declared size as the hard bound;
4. requires exact sizes and SHA-256 values, deleting failed partial artifacts; the two metadata
   checks pin the advertised source tree at handoff but do not claim to secure a later installation;
5. creates Fedora arguments for `root=/dev/mapper/live-rw`, `ifname=iso0:<mac>`, static
   `ip=...:iso0:none`, each `rd.route`, optional `nameserver`,
   `inst.repo=<origin><repository>`, `console=hvc0`, and IPv6 disablement;
6. runs `kexec -l` with fixed argv, reports `artifacts: passed` and `kexec-load: passed`, syncs, then
   runs `kexec -e`; any return from `kexec -e` runs fixed-argv `kexec -u` exactly once before
   workspace cleanup and the emergency transition. It reports the execute failure and, separately,
   whether unload also failed, so a retained loaded target is visible and never silently retried.

The network prefix is converted to a dotted netmask. The first default route supplies the gateway;
no default route or more than one is invalid for Fedora. The LPAR identifier is the hostname.
Arguments contain no whitespace and are bounded by the same 2,048-byte limit. No shell evaluation,
DHCP selector, public mirror, alternate profile, credential, or unverified executable URL is used.
All failures print one fixed stage marker and exit into the existing emergency target.

## Verification

Python tests cover version-2 structure, strict fields/bounds, canonical bytes, kernel arguments,
source preparation commands and publication races, and verifier ordering. Shell tests exercise
configuration, RAM, HTTP/size/digest, argument construction, kexec-load, kexec-exec, cleanup, and
no-DHCP failures through mocked platform boundaries; controlled faults prove new tests turn red.

`verify-fedora-evidence` accepts regular files for a canonical run record (64 KiB maximum), manifest
(64 KiB), console log (16 MiB), HTTP access log (16 MiB), packet capture (64 MiB), and two hash files
(256 bytes each). It reads at most each limit plus one byte and rejects larger, empty, symlinked, or
non-regular inputs. The version-1 run record is duplicate- and unknown-key rejecting canonical JSON
with exactly: record version; manifest digest; profile; QEMU configured MiB; guest `MemTotal` and
`MemAvailable` MiB; disk label; a map holding the SHA-256 digest of each other evidence input; and
four booleans for same-run collection, installer readiness, intended-disk visibility, and the
operator's observation that the installer UI confirmed the intended local source. Each disk hash
file is exactly 64 lowercase hexadecimal characters plus one newline.

`serve-fedora-source --directory TREE --bind ADDRESS --port PORT --access-log FILE` serves the
prepared tree with Python's standard-library HTTP server for the private VM experiment. It requires
a regular nonexistent access-log path, publishes no replacement, and records one canonical JSON
object per request with exactly method, decoded absolute path, integer status, integer response
bytes, and monotonic request index. It rejects control characters and logs no header or
client-address values. The verifier consumes only this grammar; its focused tests make real requests
to the helper and parse the bytes the helper emitted.

The verifier derives every HTTP path from the manifest, requires record identity and evidence
digests to match, requires guest `MemTotal` to meet the profile threshold, and rejects failed
requests or paths outside the selected profile and repository. It requires exactly one successful
kernel and initramfs request and at least one successful request for each derived pinned metadata
path, since Anaconda may request repository metadata again after handoff. It requires a successful
repository request other than the four launcher downloads as machine-detected corroboration of
post-kexec source activity; only the bound operator observation establishes that the ready
installer showed the intended source. It requires equal disk hashes, the existing ordered console
markers, absence of DHCP/IPv6, and all four operator observations. It reports those observations as
`operator-reviewed`, never as machine-detected; input digests prevent a reviewed record from
silently accepting replacements.

The ppc64le VM arm prepares a fresh payload and Fedora source, then boots with pSeries/POWER9,
static networking, an intended test disk attached read-only at QEMU's block boundary, and
per-netdev capture. It records exact release and artifact digests, configured RAM, guest `MemTotal`
and `MemAvailable`, installer console readiness, intended storage visibility, the intended-source UI
observation, identical disk hashes before and after, HTTP request counts, and no DHCP/IPv6.
Calibration chooses a configured VM size, records the guest-visible measurements, sets a
conservative `minimum_memory_mib` no greater than the passing guest `MemTotal`, then proves the
threshold, one MiB below it, insufficient `MemAvailable`, and insufficient `/run` space. Separate
arms exercise unreachable HTTP, wrong digest, and kexec execute and unload failures. Raw
identifiers, addresses, logs, captures, and temporary source trees remain private.

## Failure model

- **Actors and deployments:** a local operator prepares trusted Fedora media on x86_64 Linux; the
  generated launcher runs in the operator-supplied ppc64le pSeries/POWER9 VM; the local HTTP server
  and network transport may return missing, malformed, oversized, delayed, or substituted bytes.
- **Invariants and assets at stake:** executable artifacts cross kexec only after exact size and
  digest verification; the launcher emits no DHCP or IPv6 traffic; the selected profile never
  falls back; existing output paths and the read-only VM test disk are not replaced or written;
  public output contains no private configuration, network identity, or raw evidence.
- **Accepted failure classes:** bounded denial of service by a local HTTP peer is accepted because
  connection, transfer, and byte limits terminate it; repository content fetched after installer
  readiness is outside this no-installation proof and is not claimed authenticated; a missing
  ppc64le runtime tool fails preparation or launch with an actionable operation name.
- **Covered elsewhere:** manifest network validation and canonicalization remain owned by the
  version-2 parser and existing launcher checks; PowerVM firmware, VIOS mapping races, native
  storage, and live mapping cleanup remain owned by epic #1, issue #6, and a later authorized native
  run; Fedora package authentication remains owned by Fedora's installer and any later installation
  workflow.

## Threat model

- **Boundary inventory:** this design adds parsing of the caller-supplied Fedora ISO digest and
  vendor `.treeinfo`, extraction from an authenticated ISO, manifest version-2 profile fields,
  runtime HTTP responses, and bounded evidence files. It widens the existing kernel-command-line,
  dracut payload, external-tool, local-HTTP, and kexec boundaries with profile-specific values.
- **Actor model:** the local operator is trusted to supply the intended digest, manifest, HTTP
  origin, and VM invocation. The ISO before digest verification, manifest syntax, local HTTP peer,
  network transport, and evidence-file contents are untrusted. The operator-supplied VM and Fedora
  signing policy are trusted only for the explicitly recorded evidence boundary.
- **Controls per boundary:** ISO bytes are hashed before extraction; `.treeinfo`, manifests, HTTP
  responses, and evidence files are type-, grammar-, and byte-bounded; outputs publish with
  no-replace semantics; curl disables ambient configuration and redirects and uses explicit IPv4
  time and size bounds; executable and pinned metadata bytes require exact sizes and digests;
  commands use fixed argument vectors; generated kernel arguments use restricted grammars; errors
  identify the failed operation without echoing source values or downloaded content.
- **Explicitly out of scope:** issue #5 reaches installer readiness but performs no package
  installation. Authentication of later repository retrieval, Fedora package-signature policy,
  denial of service within the declared limits, malicious input deliberately approved by the
  trusted operator, native firmware policy, and physical or VIOS races remain later installation,
  vendor, operational, or native-run responsibilities named in the failure model.
