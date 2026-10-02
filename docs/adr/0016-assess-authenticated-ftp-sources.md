# ADR 0016: Carry FTP Credentials as URL Userinfo

## Status

Accepted

## Context

Epic #1 requirement 10 and issue #10 ask whether authenticated FTP can serve the launcher and the
four installer profiles, and how a credential would reach them. Today the manifest admits only
`http://` and `https://` sources without userinfo (`_validate_source` in `scripts/iso_chain.py`).
The launcher receives the source on its kernel command line (`iso_chain.source=`) and hands it to
each installer on the next one: `inst.repo=`, `iso-url=`, or `install=`
(`assets/dracut/iso-chain-launch.sh`).

Requirement 10 kept credentials out of persistent ISOs, kernel arguments, public artifacts, and
ordinary logs. No channel meets all of that without a human at the console, which the operator
rejected on 2026-10-02 because hmc-mcp console capture is output-only and holds the vterm.

## Decision

- **Userinfo in the source URL.** On 2026-10-02 the operator decided that the credential travels as
  userinfo in an `ftp://` or `ftps://` manifest `source`. The URL is written to the ISO and passes,
  unchanged, through the existing kernel-argument path to the launcher and the installer. This
  overrides requirement 10's ISO and kernel-argument clauses.
- **Where the password travels.** The operator's `--config` manifest and ADR 0015's base
  manifest, the ISO, its `--publish-dir` copy, the VIOS media repository, the launcher's and
  installer's kernel command lines and `/proc/cmdline`, the boot console and any capture of it,
  and whatever an installer logs.
- **Where it never travels.** The repository and every public artifact: commits, issues, pull
  requests, and experiment records.
- **Mitigations.** A per-run, read-only account scoped to one tree and revoked after the run; the
  ISO deleted from `--publish-dir` and the VIOS repository after the run; console captures handled
  as secret-bearing private evidence. FTPS means implicit TLS, the `ftps://` scheme, because a
  URL is the only switch every installer reads; it is preferred. Plain FTP needs the lab owner's
  written acceptance of clear-text credentials.
- **No anonymous or HTTP fallback.** An installer that cannot fetch over authenticated FTP is
  unsupported.
- **No implementation here.** The manifest keeps rejecting `ftp://` and `ftps://` until #37,
  which needs the operator's approval, implements this decision.

Specification: [Authenticated FTP assessment](../workflow/specs/2026-10-02-authenticated-ftp-assessment-design.md).

## Consequences

- **No subject is FTP-supported end to end** until #37 lands and is validated on PowerVM.
- **Secret-bearing artifacts.** A built FTP ISO and every console capture of its run must be
  handled as secrets. Anyone who can read the VIOS repository or the HMC console during the
  account's life can use it.
- **One base manifest per run.** A per-run account means a per-run base manifest, so ADR 0015's
  single base manifest for every partition no longer holds for FTP sources. #37 reconciles this.
- **Revocation is the backstop.** If an interrupted run leaves the ISO in `--publish-dir` or the
  VIOS repository, revoking the account is what bounds the exposure.
- **Password characters and length are untested.** The assessment used URL-safe passwords only.
  Percent-encoding, the characters `_validate_source` and GRUB reject, and the 2,048-byte command
  line (1,024 bytes per GRUB entry) are constraints #37 must resolve.
- **Installed-system residue is unobserved.** The assessment stops at installer readiness. #37
  checks whether an installer copies the URL onto the installed disk.

## Considered & rejected

- **A credential file appended to the kexec initrd, off the command line.** judgment: the operator
  chose the existing argument path on 2026-10-02, accepting the console and `/proc/cmdline`
  exposure in exchange for no new handoff per installer.
- **A masked launcher prompt, or typing at each installer.** judgment: the operator rejected console
  entry on 2026-10-02, because hmc-mcp console capture is output-only and holds the vterm.
- **A short-lived token on the ISO, redeemed over HTTPS for the FTP credential.** judgment: it
  needs a new redemption service, and the token is still a credential on the ISO.
- **A second, ephemeral credential medium.** judgment: mapping a second optical device needs new
  orchestration, and the operator chose the existing argument path on 2026-10-02.
- **Source-address-restricted anonymous FTP.** verified: issue #10 forbids anonymous access
  presented as FTP support.
- **Report every subject blocked without testing the installers.** judgment: issue #10 asks for
  tested outcomes, and #37 needs to know which installers can fetch over authenticated FTP.
