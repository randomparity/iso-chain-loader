# ADR 0016: Hand FTP Credentials to the Installer Only in the kexec Initrd

## Status

Accepted

## Context

Epic #1 requirement 10 and issue #10 ask whether authenticated FTP can serve the launcher and the
four installer profiles, and how a credential would reach them. The credential must stay out of
persistent ISOs, kernel arguments, public artifacts, and ordinary logs. Anonymous FTP or HTTP must
not stand in for FTP support. Today the manifest admits only `http://` and `https://` sources
(`_validate_source` in `scripts/iso_chain.py`), and no manifest field carries a credential.

The launcher (ADR 0004) fetches over the network, then `kexec`s into Anaconda, casper, or linuxrc,
which fetch again. `kexec` replaces the launcher's user space (ADR 0003), but the launcher chooses
two things the installer receives: the kernel command line and the initrd bytes
(`kexec -l … --initrd=` in `execute_kexec`, `assets/dracut/iso-chain-launch.sh`).

## Decision

- **Entry.** A human types the FTP password once, at a launcher console prompt that does not
  echo it. The user name may be typed or carried as an ordinary manifest value; it is not secret.
  Nothing is written to the manifest, ISO, a kernel argument, or a console line.
- **Handoff.** The launcher appends a small cpio archive to the downloaded installer initrd, in
  RAM, holding the installer's own source configuration with the credential: a Kickstart `url`
  for Anaconda, or a linuxrc `info` file. The kernel command line names only that file's path.
- **Per-profile support.** A profile supports authenticated FTP only if its installer reads its
  source from such a file and keeps the password out of its console and log files up to
  installer readiness. Otherwise it is unsupported or blocked, never routed to anonymous FTP or
  HTTP.
- **Credential shape.** The operator issues a per-run, read-only FTP account scoped to one source
  tree and revokes it after the run. The lab provisions it.
- **Transport.** Plain FTP sends the password in clear text. A profile claims FTP support only over
  FTPS, or over plain FTP after the lab owner accepts clear-text credentials in writing.
- **No implementation here.** The manifest keeps rejecting `ftp://` and `ftps://`. The prompt, the
  scheme, and the initrd handoff are a follow-up that needs the operator's approval.

Specification: [Authenticated FTP assessment](../workflow/specs/2026-10-02-authenticated-ftp-assessment-design.md).

## Consequences

- **No unattended FTP.** Each run needs a human at the console once, at the launcher.
- **Installed-system residue is unobserved.** The assessment stops at installer readiness. Whether
  an installer copies its source configuration, with the password, onto the installed disk is
  for the follow-up to check before any support claim beyond readiness.
- **Fedora's ISO Kickstart.** Fedora's profile already carries a Kickstart on the ISO (ADR 0011);
  the follow-up must combine it with the RAM-only source file.
- **Lab policy is an open input.** Until the lab owner rules on clear-text FTP, a profile without
  FTPS remains unsupported.

## Considered & rejected

- **Credentials in the source URL on the kernel command line.** verified: issue #10 and epic #1
  requirement 10 forbid credentials in kernel arguments; the command line is also readable as
  `/proc/cmdline` by every guest process (proc(5)).
- **Credentials in the manifest, ISO, or ISO Kickstart.** verified: the same requirement forbids
  persistent ISO payloads, and ADR 0015 links each built ISO into a `--publish-dir` by digest.
- **A Kickstart fetched at run time from an operator HTTPS endpoint.** judgment: the password then
  rests on a second server and its access path, and the fetch adds a source ADR 0011 removed.
- **Typing the credential at each installer's own prompt.** judgment: it needs a human at every
  stage and a non-echoing credential field in every installer, and it doubles the entry.
- **A second, ephemeral credential medium.** judgment: VIOS keeps uploaded media in a persistent
  repository, and mapping a second optical device needs orchestration that issue #6 owns.
- **Source-address-restricted anonymous FTP.** verified: issue #10 forbids anonymous access
  presented as FTP support.
- **Do nothing and report FTP unsupported.** judgment: the issue asks for a credential design or
  an exact blocker per profile; a bare refusal provides neither.
