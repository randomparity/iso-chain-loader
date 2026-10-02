# Authenticated FTP Assessment Design

Issue: #10 (epic #1, requirement 10). Decision: [ADR 0016](../../adr/0016-assess-authenticated-ftp-sources.md).

## Problem

Operators may hold installation trees on FTP servers that require a login. The chain fetches in
the launcher, then in one of Anaconda (Fedora 44, Rocky 9.8), casper (Ubuntu 26.04.1), or linuxrc
(openSUSE Leap 15.6). Issue #10 needs a tested outcome for the launcher and each profile, and a
credential-delivery design or an exact blocker. ADR 0016 chooses a masked launcher prompt and a
RAM-only source file appended to the installer initrd. This assessment tests whether each
installer can consume that file. It builds nothing.

## Scope

All runs use QEMU pSeries/POWER9 TCG on the x86_64 Fedora 44 development host:

- **Bootstrap arm (B).** Read the `Protocols:` line of `curl` in the `iso-chain-initramfs:44`
  image, and run `_validate_source` on an `ftp://` and an `ftps://` source.
- **Initrd arm (I): Fedora, Rocky, openSUSE.** Boot the profile's pinned installer kernel with
  `-kernel`, and as `-initrd` the pinned initrd followed by a `newc` cpio holding one source file.
  The file is a Kickstart containing `url --url=<scheme>://<user>:<password>@10.0.2.2:2121/<tree>`
  for Anaconda, or a linuxrc info file containing `install: <same URL>`. The command line is the
  launcher's handoff for that profile (`anaconda_command_line` or `opensuse_command_line` in
  `assets/dracut/iso-chain-launch.sh`) with the source argument replaced by the file's path:
  `inst.ks=file:/ftp-source.ks`, or `info=file:/ftp-source.info`. Run once with `ftp://` and once
  with `ftps://`. This is the same initrd the launcher's `kexec -l --initrd=` would hand over.
- **Transport arm (T): Ubuntu.** casper reads its source only from the command line; confirm that
  by reading its scripts in the pinned initrd. Then boot with the launcher's Ubuntu handoff and
  `iso-url=<scheme>://<user>:<password>@10.0.2.2:2121/…`, once per scheme, to record whether its
  fetch works at all. Arm T is not a delivery candidate: it puts the credential on the command
  line.
- **Readiness point.** The point each HTTP experiment of 2026-10-02 reached: the Anaconda hub with
  the source loaded, the subiquity network screen, or the YaST license screen.

The launcher is bypassed: it cannot express an FTP source without code, which the charter
excludes. Excluded, with owners: credential or FTP code (follow-up issue, operator approval),
live PowerVM and VIOS mapping (issue #6), public mirrors (epic #1), hmc-mcp ISO upload over FTP
(epic #1), and anonymous or HTTP fallback (issue #10).

### Harness

- **Server.** `pyftpdlib` 2.2.0 with `pyOpenSSL` 26.4.0 in a throwaway virtual environment outside
  the repository, bound to `127.0.0.1:2121`, passive ports `60000-60009`, masquerade address
  `10.0.2.2`, one read-only user, no anonymous user, and a self-signed certificate for FTPS. It
  starts and stops with each run and logs logins and transfers privately.
- **Network.** Default QEMU user networking, where the guest's `10.0.2.2:<port>` reaches the host's
  `127.0.0.1:<port>`, with a `filter-dump` packet capture and no DNS server configured in the
  guest. A run is valid only if every guest TCP or UDP destination in the capture is `10.0.2.2`.
- **Positive control.** Before each run, the host fetches the run's first file over the same
  scheme with `curl`. After a failed run, `ftpd.log` must show the guest's login before the run
  can count as an installer failure.
- **Log inspection.** At readiness, log in over the installer's own SSH server, reached through a
  QEMU `hostfwd` on `127.0.0.1:2222`: Anaconda with `inst.sshd` and a Kickstart `sshpw` line,
  linuxrc with `sshd=1` and `sshpassword=`. Both use a separate disposable SSH password. List
  every file under `/tmp`, `/var/log`, `/run`, and `/etc` containing the FTP password, and count
  it in `journalctl -b`. A hit in a `*.log` file, under `/var/log`, or in the journal is a log
  leak; other hits are recorded as RAM copies of the source file.
- **Credential.** One user name and password from `secrets.token_urlsafe(18)` for the whole
  assessment, kept only under private storage. The credential file, `netrc`, and argument files
  are deleted when the record is written; console and server logs remain private evidence.

### Outcome classes

Each of the five subjects (bootstrap and four profiles) gets exactly one:

- **supported** — arm I over FTPS reached readiness with the password in no console line, log
  file, or journal entry.
- **plain-FTP only** — as supported, but only over plain FTP; needs the lab owner's written
  acceptance of clear-text credentials (ADR 0016).
- **unsupported** — the guest logged in and the installer still failed the fetch, the installer
  has no file-based source input, or the password leaked; the record names which.
- **blocked** — a needed check could not run (harness fault, logs not inspectable) or needs
  excluded implementation; the record names which.

## Failure model

1. **Actors and deployments.**
   - A local operator on the development host, running QEMU TCG and the loopback server.
   - Deployment: emulator only. Native PowerVM and a lab FTP server are not run.
2. **Invariants and assets at stake.**
   - The credential must not reach the repository, a public annotation, or a pull request.
   - Each outcome must reflect an observed run or a quoted source line, never documentation alone.
3. **Accepted failure classes.**
   - Arm T puts the credential in the guest's `/proc/cmdline`, its console, and the host's QEMU
     arguments. Bounded: a read-only account over public vendor content, deleted at the end.
   - Installed-system residue is not observed, because runs stop at readiness. ADR 0016 assigns
     that check to the follow-up.
   - Emulator outcomes may differ on PowerVM. The record states the emulator boundary.
4. **Covered elsewhere.**
   - Live PowerVM and VIOS mapping: issue #6.
   - Credential implementation and installed-system residue: the follow-up issue the record
     proposes.

### Threat model

- **Boundaries.** Added: the loopback FTP server's control and data ports and the forwarded SSH
  port, reachable from the host and the guest. Widened: none; repository code is unchanged.
- **Actors.** The local operator, trusted. Other local users of the host could reach the loopback
  ports or read QEMU's arguments during a run.
- **Controls.** One read-only account with a random password; no anonymous login; servers run only
  during a run; private storage created with `umask 077`.
- **Out of scope.** Network attackers on a lab segment (no lab network is used), and plain-FTP
  confidentiality in production, which ADR 0016 leaves to the lab owner.

## Success

- One experiment record, `docs/experiments/2026-10-02-authenticated-ftp-sources.md`, gives each of
  the five subjects one outcome class, its evidence, and the exact blocker for every outcome other
  than supported.
- The record proposes the follow-up implementation for operator approval, and builds none of it.
- Before commit, a scan of every changed file finds neither the user name nor the password, nor
  the private storage path or host name.

## Validation

- **Experiment record.** Mode: `task-test-not-applicable`. Surface: a human-readable Markdown
  record. Reason: no executable consumer reads it; each outcome's evidence is the run itself,
  and `just check-markdown` checks only its form.
- **ADR 0016.** Mode: `task-test-not-applicable`. Surface: a decision record. Reason: it changes no
  executable behaviour; `_validate_source`'s scheme check is unchanged, and the bootstrap arm
  observes its rejection of `ftp://` and `ftps://` directly.
