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
  "repository": "/repository",
  "minimum_memory_mib": 4096
}
```

Artifact paths and `repository` are absolute URL paths containing only existing URI-path
characters. Sizes are integers from 1 through 2 GiB. Digests are exactly 64 lowercase hexadecimal
characters. The only accepted distribution/release pair is `fedora`/`44`. Memory is 1 through
65536 MiB. `selected_profile` must name a profile. The top-level HTTP `source` is an origin only:
scheme, canonical host, optional canonical port, and no path, query, fragment, credentials, or
trailing slash. Canonical JSON and its digest remain the immutable embedded contract.

The builder emits only the chosen profile's bounded values as `iso_chain.*` arguments and enforces
the existing 2,048-byte PowerPC command-line bound before invoking GRUB. It does not expose another
profile when a selected entry is invalid.

## Verified Fedora source preparation

`prepare-fedora-source --iso FILE --iso-sha256 DIGEST --output DIRECTORY` accepts a regular Fedora
Server 44 ppc64le DVD ISO, a trusted caller-supplied digest, and a nonexistent output. It verifies
the ISO before extraction, reads bounded `.treeinfo`, requires compose identity, architecture,
kernel, initramfs, and runtime paths, and extracts with fixed `xorriso` arguments into a private
temporary sibling directory.

Preparation copies the repository tree, creates `/profiles/fedora-44/vmlinuz`, and builds the
augmented `/profiles/fedora-44/initramfs.img`. Fedora 44's installer initramfs is an xz-compressed
`newc` archive. The augmentation appends a second xz-compressed `newc` archive containing
`/iso-chain/install.img` and an executable initqueue-settled hook. The hook sources Fedora's
existing `/usr/lib/anaconda-lib.sh`, requires the embedded runtime to be a regular file, calls
`anaconda_mount_sysroot` exactly once, and fails into the initramfs emergency shell if the expected
live-root device does not appear. Kexec supplies `root=/dev/mapper/live-rw`, so Fedora's normal
repository parser does not fetch stage2; Anaconda user space still consumes `inst.repo` for
packages. It writes a canonical `profile.json` containing release, source-ISO digest, artifact
paths, sizes, digests, and a provisional 4096 MiB minimum. A no-replace rename publishes the
completed tree. Any wrong digest, malformed metadata, missing tool/file, oversized input,
unsupported compression, or output race fails without publishing.

The Fedora download page and its signed checksum identify Server 44 compose 1.7 for ppc64le. The
DVD ISO is 3,013,869,568 bytes with SHA-256
`d0d11c768e2933a421e81db2606eafd512f9d75a15e0d591277837d2c97c908b`. That digest is evidence for
the selected release, not a value silently substituted for caller input.

## Launcher and handoff

The ppc64le payload additionally installs `sha256sum`, `kexec`, `mktemp`, `stat`, and `sync` from
the guest platform. After existing configuration, adapter, route, resolver, and HTTP checks pass,
the launcher:

1. reads `MemTotal` and rejects less than the profile minimum before artifact traffic;
2. creates a mode-0700 workspace under `/run` and refuses symlinked or non-regular destinations;
3. downloads kernel and initramfs once with curl configuration disabled, IPv4 only, no redirects,
   30-second connection timeout, 20-minute total timeout, and the declared size as the hard bound;
4. requires exact sizes and SHA-256 values, deleting a failed partial artifact;
5. creates Fedora arguments for `root=/dev/mapper/live-rw`, `ifname=iso0:<mac>`, static
   `ip=...:iso0:none`, each `rd.route`, optional `nameserver`,
   `inst.repo=<origin><repository>`, `console=hvc0`, and IPv6 disablement;
6. runs `kexec -l` with fixed argv, reports `artifacts: passed` and `kexec-load: passed`, syncs, then
   runs `kexec -e`.

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

The ppc64le VM arm prepares a fresh payload and Fedora source, then boots with pSeries/POWER9,
static networking, a snapshot virtio disk, and per-netdev capture. It records exact release and
artifact digests, the lowest tested successful RAM size, installer console readiness, intended
storage visibility, HTTP request counts, and no DHCP/IPv6. Separate arms exercise unreachable HTTP,
wrong digest, RAM below the recorded minimum, and forced kexec failure. Raw identifiers, addresses,
logs, captures, and temporary source trees remain private.

## Threat model

The local operator controls the manifest, trusted ISO digest, local HTTP origin, and VM invocation.
An untrusted ISO, manifest, HTTP peer, or network intermediary may supply malformed metadata,
oversized content, changed bytes, redirects, or sensitive values intended for logs.

- Manifest and `.treeinfo` parsing are bounded, typed, duplicate-rejecting, and allowlist-only.
- Source preparation authenticates the ISO before using its executable contents and publishes only
  after complete extraction and metadata generation.
- Runtime HTTP is fixed to the manifest origin, disables ambient curl configuration and redirects,
  bounds time and bytes, and authenticates kernel plus augmented initramfs before kexec.
- External commands receive fixed argv lists; paths and Fedora arguments pass restricted grammars.
- Errors name the failed operation without echoing URLs, configuration, downloaded bytes, or raw
  console content.

Package-repository availability, Fedora package-signature policy, denial of service within the
declared bounds, malicious trusted operator input, native firmware policy, and physical/VIOS races
are outside this design. The first three are operational or vendor boundaries; the latter two are
unreachable in the VM-only run.
