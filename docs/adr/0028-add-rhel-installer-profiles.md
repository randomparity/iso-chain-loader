# ADR 0028: Add RHEL Installer Profiles

## Status

Accepted

> **Amended by [ADR 0031](0031-install-rhel-unattended-from-a-derived-kickstart.md)**
> (2026-10-16): login values are accepted for `rhel`, which then installs unattended.

## Context

Issue #78 asks for Red Hat Enterprise Linux profiles. Issue #7 chose Rocky as a RHEL surrogate on
2026-10-02 (ADR 0013), so `rhel` is rejected today. On 2026-10-15 the operator decided that every
RHEL 9 and RHEL 10 release the operator's authenticated FTP mirror offers for ppc64le is supported,
that the profile is interactive like Rocky, and that the 10.x profiles ship whatever a POWER9 boot
shows.

The mirror's BaseOS tree matches Rocky's: `BaseOS/ppc64le/os` holds `.treeinfo`, `repodata/`,
`images/install.img`, and `ppc/ppc64/vmlinuz` and `initrd.img`. verified: `curl` of each of the
twelve trees' `.treeinfo` on the operator's mirror on 2026-10-15 returned family
`Red Hat Enterprise Linux`, the tree's own version, the `ppc/ppc64/vmlinuz` kernel, and no
`[variant-AppStream]` section. Three differences matter:

- **No signed anchor.** The mirror publishes only `<iso>.SHA256SUM` files and the `.treeinfo`
  `[checksums]`. Neither is signed, and the tree has no `repomd.xml.asc`.
- **No AppStream in `.treeinfo`.** BaseOS's `.treeinfo` has only `[variant-BaseOS]`, so Anaconda
  does not add AppStream by itself, unlike Rocky's.
- **Releases.** The mirror offers 9.0 to 9.8 and 10.0 to 10.2.

## Decision

- **Profile shape.** A `rhel` profile carries exactly `kernel`, `initramfs`, `repository`, and
  `minimum_memory_mib`, with Rocky's grammar and no `kickstart`. `repository.path` must end in
  `/BaseOS/ppc64le/os`. `release` is one of 9.0 to 9.8 or 10.0 to 10.2, a closed list. Manifest
  version stays `4`. Login values stay refused for `rhel` until an unattended profile exists.
- **Trust anchor.** `prepare-rhel-source` takes the boot ISO digest the operator read from the
  mirror's `SHA256SUM` and requires `--digest-source mirror-sha256sum`, the only accepted value, so
  the weaker anchor is never implied. It guards against corruption and drift, not against a
  compromised mirror. The command prints `digest-source: mirror-sha256sum` and writes nothing into
  `profile.json`, because a manifest rejects unknown fields.
- **Handoff.** The launcher runs Rocky's Anaconda arguments with no `inst.ks`, plus one
  `inst.addrepo=AppStream,<source><path>` that swaps `/BaseOS/ppc64le/os` for
  `/AppStream/ppc64le/os`.
- **Evidence.** The installer arguments must carry exactly those two repository arguments, and
  post-kexec HTTP traffic may reach only BaseOS and the AppStream sibling.
- **Mirror identity.** No document or test names the operator's mirror. Examples use the
  placeholder `<REDACTED-FTP-MIRROR>`; the mirror is only `source` in a private manifest.
- **Adding a release.** A new release is an edit to `RHEL_RELEASES`, the error message, the
  launcher's `case` pattern, and their tests. The launcher's shell test runs every listed release
  and the boundary values around it, so a pattern that drifts from the list fails.

Specification: [RHEL installer profiles](../workflow/specs/2026-10-15-rhel-profiles-design.md).

## Consequences

- **Accepted risk: a compromised mirror.** The digest is only as good as the operator's own check,
  for example against Red Hat's published checksums.
- **Accepted risk: unpinned stage2, BaseOS repository metadata beyond `repomd.xml`, and AppStream**,
  the ADR 0011 and 0013 class.
- **Unverified: `inst.addrepo` on every release.** Anaconda documents it upstream. Whether RHEL
  9.0 to 10.2 honour it is proved only for the releases booted live, by AppStream appearing in the
  installer's Installation Source screen; the other ten releases are untested.
- **RHEL 10 on POWER9.** Issue #78 and ADR 0013 state that RHEL 10 on ppc64le needs POWER10; this
  record did not verify that. The 10.x profiles ship, and a POWER9 boot result is recorded in
  `docs/experiments/`. A profile that boots is not a statement that the release supports the host.
- **Interactive only.** The unattended Kickstart is a follow-up issue.

## Considered & rejected

- **Reuse the `rocky` profile for RHEL.** judgment: the AppStream handling, the identity checked in
  `.treeinfo`, and the release set differ, and a profile named for the wrong distribution misleads
  the evidence.
- **Accept any `9.<n>` or `10.<n>`.** judgment: it would admit releases nobody listed or tested,
  against the no-fallbacks rule.
- **Require a signed digest.** verified: `curl` listings of the RHEL 9.8 and 10.2 trees on the
  operator's mirror on 2026-10-15 showed no `.asc`, `.sig`, `.gpg`, or `CHECKSUM` file and no
  `repomd.xml.asc`; the other ten releases were not listed and are assumed alike. The operator
  chose the mirror's `SHA256SUM` on 2026-10-15.
- **Record the digest source in `profile.json`.** verified: `_manifest_object` in
  `scripts/iso_chain.py` raises `unknown field` for any key outside the field set, and operators
  paste `profile.json` into a manifest.
- **A separate `rhel-mirror` command or distribution.** judgment: the weaker anchor belongs to the
  digest's source, not to a host, and a required flag already makes it explicit.
- **BaseOS only, no AppStream.** judgment: the operator chose to include AppStream on 2026-10-15,
  since most software selections need it.
