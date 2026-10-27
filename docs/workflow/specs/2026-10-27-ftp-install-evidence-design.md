# FTP installation evidence

Issue #77; scope q77-9e43ac96, Campaign 8220ba201632-a93eca58-dabd-4800-9728-fe86d31fe402.

## Problem and authority

The Fedora, Rocky and Ubuntu installation verifiers accept only the HTTP JSON-lines access log.
Changing a manifest source to FTP does not make those GET records FTP evidence. Issue #77 and the
operator's 2026-10-27 approval authorize real FTP server transfer logs, privacy-safe refusals,
and format selection here. [ADR 0027](../../adr/0027-accept-plain-ftp-sources-with-userinfo.md)
records the selected contract. HTTP evidence and launcher-readiness verification are preserved.

## Architecture and contracts

Extend the existing shared installation verifier; no ownership transition or new command is needed.
For an FTP manifest, `--access-log` reads a raw standard xferlog, bounded by `MAX_LOG_BYTES`.
The manifest scheme selects the parser: there is no sniffing, fallback or synthetic HTTP record.
The existing version-1 installation record and `evidence_sha256.access_log` bind the exact raw bytes.
No normalized artifact, extra digest, log-format field or record version is necessary: the already
bound manifest disambiguates the format. The operator's existing same-run assertion remains required.

Support the standard 18-token xferlog form emitted by vsftpd, with filenames relative to the
FTP account's chroot namespace (leading slash). Its five timestamp tokens, duration, remote IPv4,
transferred-byte count, filename, binary mode, action, outbound direction, real-user access,
username, service, authentication fields and complete status are validated. Admit only
`b _ o r USER ftp 0 * c`; reject incomplete, ASCII, upload, anonymous and transformed transfers.
The decoded username must be printable ASCII without whitespace for this supported format.
Compare username bytes with the percent-decoded manifest username. Do not decode paths: the existing
canonical ASCII URL-path grammar applies to the server filename, including RPM `+` and `@`.
Remove only the manifest source path prefix, on a slash boundary, before matching artifact paths.
Servers logging host filesystem paths must expose the account in a matching chroot namespace;
this change adds no configurable mapping or normalization path.

The FTP parser yields `(path, bytes)` transfers, never GET/status dictionaries. For Fedora/Rocky,
the initial transfers must match the launcher's ordered pins and exact sizes; kernel/initramfs
occur once, later transfers stay under the selected repository prefixes, and later traffic is
required. Rocky retains its BaseOS/AppStream prefixes. Ubuntu requires exactly kernel, initramfs,
and live ISO in order at pinned sizes. This shares profile/artifact helpers with HTTP, while the
HTTP parser and request policies remain unchanged. Success emits `ftp-evidence: passed` for FTP
and retains `http-evidence: passed` for HTTP(S). The three install CLI help descriptions cover both.

Refusals name only fixed rules, with no URL, username, filename, remote host or raw record.
The raw private server log and console/capture remain secret-bearing evidence. No log is published.

## Global Constraints

Python 3.14; stdlib runtime only; macOS arm64 and x86_64 Linux development hosts; ppc64le POWER9 target.
No new dependencies; preserve HTTP behavior, existing evidence bounds and canonical record grammar.

## Success

- Genuine standard transfer logs pass the three installation verifiers with their bound inputs.
- Wrong account, source prefix, transfer direction/completion, order, size, record grammar or digest
  fails without echoing input; HTTP logs cannot substitute for FTP transfers and vice versa.
- Existing HTTP installation behavior and the record's exact field/digest sets remain intact.
- README provides the supported server-log settings/namespace and same-run collection requirements.

## Failure model

1. Actors and deployments:
   - Local operator reviewing private QEMU install evidence; CI exercises bounded synthetic cases.
   - The source FTP server is operator controlled; supported logs come from a dedicated per-run account.
2. Invariants and assets at stake:
   - Evidence must corroborate completed selected-profile transfers; refuse malformed/unrelated input.
   - Credentials and private log fields must not reach CLI refusals or public output.
3. Accepted failure classes:
   - Standard transfer logs cannot prove absent failed control commands or reconstruct content hashes;
     launcher pins, console checks, process/disk evidence and operator review retain those boundaries.
   - A dishonest operator can fabricate a digest-bound evidence set; hashes bind reviewed inputs,
     not independent server identity, chronology or authenticity. Same-run provenance is reviewed.
   - Non-ASCII/whitespace usernames and servers with incompatible log path namespaces
     are unsupported inputs.
4. Covered elsewhere:
   - FTPS, provisioning, alternative credential channels and FTP stream reconstruction: operator.
   - Full live installs: #70; native PowerVM: #72; readiness expansion: separate operator decision.

## Threat model

- Added boundary: raw FTP server log to local verifier; operator supplies potentially malformed bytes.
- Existing boundaries widened: existing access-log input now has a manifest-selected FTP interpretation.
- Controls: regular no-symlink bounded reads and exact raw digest binding precede parsing; fixed token
  grammar, bounded integers, canonical paths, account match and transfer/profile policy fail closed.
  Fixed error text exposes no raw fields. Existing pcap and console/disk/process verification remain.
- Trust: operator owns server/account and same-run collection; an on-path FTP attacker remains the
  accepted ADR 0027 risk. Packet stream reconstruction and server provisioning are excluded above.

## Validation

Use the matching installation test fixtures and real boundary mocks only for tcpdump. Add focused
FTP acceptance tests for Fedora, Rocky and Ubuntu, then malformed/partial/account/prefix/path/order/
size/digest/privacy cases. Confirm new tests fail against the old HTTP-only implementation; confirm
sensitive rejection tests bite by disabling a guard temporarily and reverting it. Run a small real
FTP transfer with a throwaway server and feed its untouched xferlog into the parser/policy; no full
install is claimed. Run focused classes, then `just check` on the assembled branch. CI covers Linux
and macOS; full QEMU installs remain #70. The transient plan carries the per-contract commands.
