# ADR 0006: Bind Unattended Installation in Manifest Version 3

## Status

Accepted

## Context

Issue #17 must extend the Fedora 44 ppc64le launcher from an interactive, no-write installer proof
to a reproducible unattended installation and a subsequent disk-only boot. Manifest version 2 has
an exact-field schema and authenticates the installer kernel and initramfs, but carries no
Kickstart identity. Its evidence record intentionally requires an unchanged disk and therefore
cannot describe installation success.

The repository has no compatibility commitment for its pre-release manifest or evidence formats.
The new workflow must keep the interactive proof usable, prevent writes to its backing image, and
make a marker in a second QEMU process stronger evidence than text emitted during installation.

## Decision

Replace manifest version 2 with strict version 3. Each Fedora profile gains a required `kickstart`
artifact with canonical URL path, exact byte size, and SHA-256 digest. Fedora source preparation
accepts one caller-supplied regular Kickstart file, bounds it to 1 MiB, publishes it at
`/profiles/fedora-44/ks.cfg`, and emits its identity in `profile.json`. The launcher downloads and
verifies that fifth artifact before kexec and supplies its local URL through `inst.ks`.

Keep `smoke` and `verify-fedora-evidence` as the pre-installation proof, adapting them to version 3
without changing their unchanged-disk conclusion. Add a separate `install-fedora` workflow and
`verify-fedora-install-evidence` contract. The install workflow creates a fresh qcow2 copy-on-write
overlay over a caller-supplied qcow2 backing disk with an explicit backing format, runs an
ISO-attached installation phase, then runs a disk-only boot phase against that overlay. Each phase
has its own bounded console log and packet capture.

Ship one Fedora 44 Kickstart fixture that limits destructive storage commands to `/dev/vda`, powers
off after installation, writes a durable completion token, and enables a oneshot service. On the
subsequent boot the service requires that token, emits a fixed marker with the kernel boot ID on
the console, and powers off. The installation verifier binds the canonical manifest, Kickstart,
HTTP access log, both console logs, both filtered captures, immutable backing-disk hashes, changed
overlay hashes, and the operator's same-run assertion.

## Consequences

Old manifests fail explicitly instead of silently running without automation. Preparation and
launcher tests gain one more bounded artifact and request. The command-line budget remains 2,048
bytes and now includes three Kickstart arguments.

The backing disk remains unchanged because QEMU writes only to the new overlay; QEMU documents that
a backing file is not modified by a copy-on-write image unless an explicit commit operation is
used. The workflow exposes no commit operation. A completed second boot proves that the installed
filesystem contains the token and service created by `%post`; installer console text alone cannot
satisfy the verifier.

The reference Kickstart is intentionally Fedora-44- and `/dev/vda`-specific. Other distributions,
releases, storage layouts, and native PowerVM execution require separately authorized work.

## Considered & rejected

- **Add an optional Kickstart field to manifest version 2.** judgment: optional automation would
  make the same version describe both interactive and unattended behavior and weaken exact-schema
  failures; this pre-release contract has no compatibility consumer requiring that ambiguity.
- **Serve an unbound Kickstart sidecar.** judgment: the evidence could no longer prove that the
  requested and installed configuration was the caller-reviewed file.
- **Treat installer process exit as installation success.** verified: issue #17 requires a
  subsequent disk-only boot into a machine-detectable success state, so process exit alone omits a
  sourced completion criterion.
- **Write directly to the supplied disk.** verified: QEMU's `qemu-img create` documentation states
  that a qcow2 backing file is not modified absent an explicit commit; the approved exclusion set
  forbids modifying an existing VM image, making a fresh overlay the matching primitive.
- **Use a guest agent for the success signal.** judgment: it adds a guest/runtime protocol and
  dependency when the existing serial console already provides a bounded evidence channel.
- **Do nothing.** verified: manifest version 2 has no Kickstart artifact and the existing experiment
  stops before installation, as recorded by issue #17 and the Fedora installer experiment.
