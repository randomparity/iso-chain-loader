# ADR 0016: Deliver FTP Credentials Only by Console Entry

## Status

Accepted

## Context

Epic #1 requirement 10 and issue #10 ask whether authenticated FTP can serve the launcher and the
four installer profiles, and how a credential would reach them. The credential must stay out of
persistent ISOs, kernel arguments, public artifacts, and ordinary logs. Anonymous FTP or HTTP must
not stand in for FTP support. Today the manifest admits only `http://` and `https://` sources
(`_validate_source` in `scripts/iso_chain.py`), and no manifest field carries a credential.

The chain has three stages that each fetch on their own: the launcher (ADR 0004), and then, after
`kexec`, either Anaconda, casper, or linuxrc. `kexec` replaces the launcher's user space (ADR 0003).
The only state the launcher hands to an installer is the new kernel command line, which is the
channel the requirement forbids for a secret.

## Decision

- **Delivery channel.** A credential reaches a stage only by a human typing it on that stage's
  console at run time. It is held in memory or `tmpfs` by the stage that uses it, and is never
  written to the manifest, the ISO, a Kickstart, a kernel argument, or a console line.
- **Per-stage authentication.** Each stage that fetches over FTP authenticates on its own. A
  stage that offers no console credential entry cannot use authenticated FTP, and its profile is
  reported as unsupported, not routed to anonymous FTP or HTTP.
- **Credential shape.** The operator issues a per-run, read-only FTP account scoped to the one
  source tree and revokes it after the run. That account is the lab's to provision.
- **Transport.** Plain FTP sends the credential in clear text. A profile claims FTP support only
  over FTPS, or over plain FTP after the lab owner accepts clear-text credentials on the
  installation network in writing.
- **No implementation here.** The manifest keeps rejecting `ftp://` and `ftps://`. A launcher
  prompt, a manifest scheme, and any per-profile handoff change are a follow-up that needs the
  operator's approval.

Specification: [Authenticated FTP assessment](../workflow/specs/2026-10-02-authenticated-ftp-assessment-design.md).

## Consequences

- **No unattended FTP.** Console entry needs a human at the HMC console for every stage. The
  unattended Fedora Kickstart path cannot use authenticated FTP.
- **Repeated entry.** Where both the launcher and the installer fetch over FTP, the operator types
  the credential twice.
- **Per-profile outcome.** Whether a profile is supported depends on its installer's own console
  entry and logging behaviour. The experiment record holds those outcomes.
- **Lab policy is an open input.** Until the lab owner rules on clear-text FTP, a profile without
  FTPS remains unsupported.

## Considered & rejected

- **Credentials in the source URL on the kernel command line.** verified: issue #10 and epic #1
  requirement 10 forbid credentials in kernel arguments; the command line is also readable as
  `/proc/cmdline` by every guest process (proc(5)).
- **Credentials in the manifest, ISO, or Kickstart.** verified: the same requirement forbids
  persistent ISO payloads, and ADR 0015 links each built ISO into a `--publish-dir` by digest.
- **A second, ephemeral credential medium.** judgment: VIOS keeps uploaded media in a persistent
  repository, and mapping a second optical device needs orchestration that issue #6 owns.
- **Source-address-restricted anonymous FTP.** verified: issue #10 forbids anonymous access
  presented as FTP support.
- **The launcher fetches everything and the installers use local copies.** judgment: every
  installer reads its repository after `kexec`, which the launcher cannot proxy across.
- **Do nothing and report FTP unsupported.** judgment: the issue asks for a credential design or
  an exact blocker per profile; a bare refusal provides neither.
