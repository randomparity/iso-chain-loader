# Authenticated FTP Assessment Design

Issue: #10 (epic #1, requirement 10). Decision: [ADR 0016](../../adr/0016-assess-authenticated-ftp-sources.md).
Follow-up: #37.

## Problem

Operators may hold installation trees on FTP servers that require a login. ADR 0016 carries the
credential as userinfo in an `ftp://` or `ftps://` source URL, through the ISO and the existing
kernel-argument path. Issue #10 needs a tested outcome for the launcher and each installer profile:
Fedora 44 and Rocky 9.8 (Anaconda), Ubuntu 26.04.1 (casper), and openSUSE Leap 15.6 (linuxrc).
This assessment builds nothing; #37 implements the decision.

## Scope

All guest runs use QEMU pSeries/POWER9 TCG on the x86_64 Fedora 44 development host.

- **Bootstrap arm (B).** In the `iso-chain-initramfs:44` image, run the launcher's `curl` with the
  flags of `download_artifact` against the loopback server, fetching the Fedora kernel through a
  userinfo URL over each scheme, and compare its SHA-256 with the pin. Run `_validate_source` on an
  `ftp://` and an `ftps://` source.
- **Handoff arm (H), per profile.** Boot the profile's pinned installer kernel and initrd with
  QEMU `-kernel`/`-initrd` and the launcher's handoff arguments for that profile
  (`anaconda_command_line`, `ubuntu_command_line`, `opensuse_command_line`), with the source URL
  replaced by `<scheme>://<user>:<password>@10.0.2.2:2121/<tree>`. Fedora runs without its ISO
  Kickstart, so it stops at the interactive hub like Rocky. Run once per scheme.
- **Readiness point.** The point each HTTP experiment of 2026-10-02 reached: the Anaconda hub with
  the source loaded, the subiquity network screen, or the YaST license screen.

The launcher itself is bypassed: it cannot accept an FTP source without the code #37 owns.
Excluded, with owners: FTP or credential code (#37, operator approval); live PowerVM and VIOS
mapping (#37); public mirrors (epic #1); hmc-mcp ISO upload over FTP (epic #1); anonymous or HTTP
fallback (issue #10).

### Harness

- **Server.** `pyftpdlib` 2.2.0 with `pyOpenSSL` 26.4.0 in a throwaway virtual environment outside
  the repository, bound to `127.0.0.1:2121`, passive ports `60000-60009`, masquerade address
  `10.0.2.2`, one read-only user, no anonymous user. FTPS uses a certificate with
  `subjectAltName=IP:10.0.2.2` issued by a throwaway CA. The server starts and stops with each run
  and logs logins and transfers privately.
- **Credential.** A fresh user name and password from `secrets.token_urlsafe(18)` for each run,
  kept under private storage and deleted after the record is written.
- **Network.** Default QEMU user networking, where the guest's `10.0.2.2:<port>` reaches the host's
  `127.0.0.1:<port>`, with a `filter-dump` packet capture. A run is valid only if every guest TCP
  or UDP destination in the capture is `10.0.2.2`.
- **Positive control.** Before each run, the host fetches the run's first file over the same
  scheme with `curl --cacert` and the throwaway CA.
- **FTPS trust.** No installer trusts the throwaway CA. If an FTPS run fails before login, rerun it
  once with the installer's own verification switch off (`inst.noverifyssl`, linuxrc
  `ssl.certs=0`) where one exists. The record reports both results: a pass only without
  verification is a named trust constraint for #37, not FTPS support.

### Outcome classes

Each of the five subjects gets exactly one of criterion 1's terms:

- **supported** — the installer reached readiness over at least one scheme. It means installer-side
  support under the emulator, never end-to-end support; the record says so on every row.
- **unsupported** — `ftpd.log` shows the guest's login or TLS handshake, yet the installer failed
  the fetch over both schemes; the record quotes the installer's error.
- **blocked** — the result cannot be decided here: the bootstrap needs #37's code, or the run
  had no server contact or an invalid capture, after one rerun.

For each run the record also counts the password in the console log, as a disclosure of where it
travels rather than a grading input.

## Failure model

1. **Actors and deployments.**
   - A local operator on the development host, running QEMU TCG and the loopback server.
   - Deployment: emulator only. Native PowerVM and a lab FTP server are not run.
2. **Invariants and assets at stake.**
   - The test credential must not reach the repository, a public annotation, or a pull request.
   - Each outcome reflects an observed run, never documentation alone.
3. **Accepted failure classes.**
   - The test credential appears in the guest's `/proc/cmdline`, the console log, and the host's
     QEMU arguments. Accepted by ADR 0016 for the real path; here it is a read-only account over
     public vendor content, rotated per run.
   - Installer log files and installed-system residue are not inspected. ADR 0016 accepts the
     password in installer logs; #37 checks installed-system residue.
   - Emulator outcomes may differ on PowerVM. The record states the emulator boundary.
4. **Covered elsewhere.**
   - Implementation, mitigations, residue, and live PowerVM validation: #37.

### Threat model

- **Boundaries.** Added: the loopback FTP server's control and data ports, reachable from the host
  and the guest. Widened: none; repository code is unchanged.
- **Actors.** The local operator, trusted. Other local users of the host could reach the loopback
  ports or read QEMU's arguments during a run.
- **Controls.** A read-only account with a random password per run; no anonymous login; the server
  runs only during a run; private storage created with `umask 077`.
- **Out of scope.** Exposure of a real credential through the ISO, console, and kernel arguments,
  which ADR 0016 accepts and #37 mitigates.

## Success

- One experiment record, `docs/experiments/2026-10-02-authenticated-ftp-sources.md`, gives each of
  the five subjects one outcome with its evidence, names every trust or transport constraint, and
  states that no subject is FTP-supported end to end until #37.
- Before commit, a scan of every changed file finds none of the run credentials, the private
  storage path, or the host name.

## Validation

- **Experiment record.** Mode: `task-test-not-applicable`. Surface: a human-readable Markdown
  record. Reason: no executable consumer reads it; each outcome's evidence is the run itself,
  and `just check-markdown` checks only its form.
- **ADR 0016.** Mode: `task-test-not-applicable`. Surface: a decision record. Reason: it changes no
  executable behaviour; `_validate_source`'s scheme check is unchanged, and the bootstrap arm
  observes its rejection of `ftp://` and `ftps://` directly.
