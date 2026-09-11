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
The new workflow must keep the interactive proof usable, accept no caller-supplied install disk,
and make a marker in a second QEMU process stronger evidence than text emitted during installation.

## Decision

Replace manifest version 2 with strict version 3. Each Fedora profile gains a required `kickstart`
artifact with canonical URL path, exact byte size, and SHA-256 digest. Fedora source preparation
accepts one caller-supplied regular Kickstart file, bounds it to 1 MiB, publishes it at
`/profiles/fedora-44/ks.cfg`, embeds the same bytes at `/iso-chain/ks.cfg` in the authenticated
installer initramfs, and emits its identity in `profile.json`. The launcher downloads and verifies
the published copy before kexec, then supplies `inst.ks=file:/iso-chain/ks.cfg` so Anaconda consumes
the exact embedded bytes instead of a second network response.

Keep `smoke` and `verify-fedora-evidence` as the pre-installation proof, adapting them to version 3
without changing their unchanged-disk conclusion. Add a separate `install-fedora` workflow and
`verify-fedora-install-evidence` contract. The install workflow creates a fresh standalone qcow2 of
a bounded requested size, runs an ISO-attached installation phase with a network capture, then runs
a disk-only boot phase against that disk with no network adapter. Each phase has a bounded console
log. Because filter-dump has no total-byte bound, it writes to a private FIFO and a parent-owned
reader retains no more than 8 GiB before terminating the phase as an overflow.

Ship one Fedora 44 Kickstart fixture that limits destructive storage commands to `/dev/vda`, powers
off after installation, writes a durable completion token, and enables a oneshot service. On the
subsequent boot the service requires that token, emits a fixed marker with the kernel boot ID on
the console, and powers off. The installation verifier binds the canonical manifest, Kickstart,
HTTP access log, both console logs, the filtered install capture, a canonical process-result record,
changed standalone-disk hashes, and the operator's same-run assertion.

## Consequences

Old manifests fail explicitly instead of silently running without automation. Preparation and
launcher tests gain one more bounded artifact and request. The command-line budget remains 2,048
bytes and now includes three Kickstart identity arguments plus the fixed local `inst.ks` argument.

No external disk can be modified because the command accepts no disk input; QEMU writes only to the
fresh standalone image in private staging. A completed second boot proves that the installed
filesystem contains the token and service created by `%post`; installer console text alone cannot
satisfy the verifier.

The reference Kickstart is intentionally Fedora-44- and `/dev/vda`-specific. Other distributions,
releases, storage layouts, and native PowerVM execution require separately authorized work. The
retained raw install capture has a process-owned 8 GiB hard ceiling; reaching it fails the run.

## Considered & rejected

- **Add an optional Kickstart field to manifest version 2.** judgment: optional automation would
  make the same version describe both interactive and unattended behavior and weaken exact-schema
  failures; this pre-release contract has no compatibility consumer requiring that ambiguity.
- **Serve an unbound Kickstart sidecar.** judgment: the evidence could no longer prove that the
  requested and installed configuration was the caller-reviewed file.
- **Treat installer process exit as installation success.** verified: issue #17 requires a
  subsequent disk-only boot into a machine-detectable success state, so process exit alone omits a
  sourced completion criterion.
- **Create an overlay over a supplied disk.** judgment: even an unchanged backing image could
  preseed the success token or service and create a false positive; accepting no disk input makes
  the install start state explicit and enforces the approved disposable-storage boundary.
- **Use a guest agent for the success signal.** judgment: it adds a guest/runtime protocol and
  dependency when the existing serial console already provides a bounded evidence channel.
- **Do nothing.** verified: manifest version 2 has no Kickstart artifact and the existing experiment
  stops before installation, as recorded by issue #17 and the Fedora installer experiment.
