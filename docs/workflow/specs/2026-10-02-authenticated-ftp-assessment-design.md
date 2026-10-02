# Authenticated FTP Assessment Design

Issue: #10 (epic #1, requirement 10). Decision: [ADR 0016](../../adr/0016-assess-authenticated-ftp-sources.md).

## Problem

Operators may hold installation trees on FTP servers that require a login. The chain fetches in
three stages: the launcher, then one of Anaconda (Fedora 44, Rocky 9.8), casper (Ubuntu 26.04.1),
or linuxrc (openSUSE Leap 15.6). Issue #10 needs a tested compatibility outcome for the launcher
and each profile, and a credential-delivery design or an exact blocker. It builds nothing.

## Scope

In scope, all under QEMU pSeries/POWER9 TCG on the x86_64 Fedora 44 development host:

- **Bootstrap arm.** Read the protocols of `curl` in the `iso-chain-initramfs:44` image, and run
  the manifest validator on an `ftp://` and an `ftps://` source.
- **Transport arm (T), per profile.** Boot the profile's pinned installer kernel and initrd
  directly with QEMU `-kernel`/`-initrd`, using the launcher's handoff arguments for that profile
  (`anaconda_command_line`, `ubuntu_command_line`, `opensuse_command_line` in
  `assets/dracut/iso-chain-launch.sh`) with the source URL changed to
  `ftp://<user>:<password>@10.0.2.2:2121/<path>`. Repeat once with `ftps://` where the installer
  accepts that scheme. This shows whether the installer's FTP client works; it is not a delivery
  candidate, because it puts the credential on the command line.
- **Console-entry arm (C), per profile.** Boot without any credential and look for the installer's
  own interactive source entry: Anaconda's text Installation Source spoke, linuxrc's manual-mode
  FTP dialog, and casper's boot scripts (read from its initrd, since casper has no dialog). Where
  an entry exists, type the credential there and drive to the same readiness point.
- **Readiness point.** The point each HTTP experiment of 2026-10-02 reached: the Anaconda hub
  with the source loaded, the subiquity network screen, or the YaST license screen.

The launcher is bypassed in arms T and C: it cannot express an FTP source without code, which the
charter excludes. Its handoff arguments are reused unchanged apart from the source.

Excluded, with owners: credential or FTP code (follow-up issue, operator approval), live
PowerVM and VIOS mapping (issue #6), public mirrors (epic #1), hmc-mcp ISO upload over FTP
(epic #1), and anonymous or HTTP fallback (issue #10).

### Harness

- **Server.** `pyftpdlib` 2.2.0 with `pyOpenSSL` 26.4.0 in a throwaway virtual environment
  under private storage, outside the repository. It binds `127.0.0.1:2121` with passive ports
  `60000-60009`, a masquerade address of `10.0.2.2` (QEMU user-mode network's host alias), one
  read-only user, no anonymous user, and a private self-signed certificate for FTPS. It logs
  logins and transfers to a private file.
- **Credential.** A fresh 24-character user name and password from `secrets.token_urlsafe` per
  run, stored only in a `0600` file under private storage, deleted when the run's evidence is
  recorded. The served tree is a local copy of public vendor content.
- **Trees.** Fedora and Rocky: `.treeinfo`, `images/install.img`, the boot kernel and initrd, and
  `repodata/` (Rocky also AppStream's `repodata/`). openSUSE: the subset listed in its 2026-10-02
  experiment. Ubuntu: the live-server ISO. Kernel, initrd, and ISO digests must equal the values
  recorded in the 2026-10-01 and 2026-10-02 experiment records before a run.

### Outcome classes

Each of the five subjects (bootstrap and four profiles) gets exactly one:

- **supported** — arm C reached readiness over FTPS with no credential in the console log.
- **plain-FTP only** — arm C reached readiness only over plain FTP; it needs the lab owner's
  written acceptance of clear-text credentials (ADR 0016).
- **unsupported** — no console entry exists, the FTP fetch failed, or the credential appeared in
  the console log. The record names which.

## Failure model

1. **Actors and deployments.**
   - A local operator on the development host, running QEMU TCG and the loopback server.
   - Deployment: emulator only. Native PowerVM and a lab FTP server are not run.
2. **Invariants and assets at stake.**
   - The disposable credential must not reach the repository, a public annotation, or a pull
     request.
   - Each outcome must reflect an observed run, never documentation alone.
3. **Accepted failure classes.**
   - The credential appears in the guest's `/proc/cmdline` and console during arm T. Bounded:
     the credential is disposable, the server is loopback-only, and arm T is not a delivery
     candidate. For the same reason it is visible in the host's QEMU process arguments.
   - Installer log files not shown on the console are not inspected. Bounded: the record states
     that the absence of a leak was checked on the console only.
   - Emulator outcomes may differ on PowerVM. The record states the emulator boundary.
4. **Covered elsewhere.**
   - Live PowerVM and VIOS mapping: issue #6.
   - Credential implementation: the follow-up issue named in the experiment record.

### Threat model

- **Boundaries.** Added: the loopback FTP server's control and data ports, reachable from the
  host and the QEMU guest. Widened: none; repository code is unchanged.
- **Actors.** The local operator, trusted. Other local users of the host could connect to the
  loopback ports during a run.
- **Controls.** One read-only account with a fresh random password; no anonymous login; the
  server stops when the run ends; credential file `0600` and deleted afterwards.
- **Out of scope.** Network attackers on a lab segment (no lab network is used), and the
  confidentiality of plain-FTP credentials in production, which ADR 0016 leaves to the lab owner.

## Success

- One experiment record, `docs/experiments/2026-10-02-authenticated-ftp-sources.md`, gives each of
  the five subjects one outcome class with its observed evidence and the exact blocker for every
  non-supported outcome.
- The record proposes the follow-up implementation for operator approval, and builds none of it.
- No credential, private path, or host identifier appears in the repository or a public comment.

## Validation

- **Experiment record.** Mode: `task-test-not-applicable`. Surface: a human-readable Markdown
  record. Reason: no executable consumer reads it; each outcome's evidence is the run itself,
  and `just check-markdown` checks only its form.
- **ADR 0016.** Mode: `task-test-not-applicable`. Surface: a decision record. Reason: it changes no
  executable behaviour; `_validate_source`'s scheme check is unchanged, and the bootstrap arm
  observes its rejection of `ftp://` and `ftps://` directly.
