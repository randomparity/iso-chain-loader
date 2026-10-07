# FTP Source Design

Issue: #68 (epic #37). Decision: [ADR 0027](../../adr/0027-accept-plain-ftp-sources-with-userinfo.md),
with [ADR 0016](../../adr/0016-assess-authenticated-ftp-sources.md) for the credential's
path and [ADR 0026](../../adr/0026-restrict-plain-http-to-private-ipv4-sources.md) for plain HTTP.

## Problem

`_validate_source` (`scripts/iso_chain.py`) and the launcher's `valid_source`
(`assets/dracut/iso-chain-launch.sh`) refuse every `ftp://` source, so ADR 0027's grammar cannot
be used. Both must accept it under one rule and keep the credential out of every refusal.

## Scope

In scope:

- `scripts/iso_chain.py`: `_validate_source` gains an `ftp://` branch. It splits the remainder at
  the first `@`, checks the userinfo with a new `_validate_ftp_userinfo`, and validates
  `https://<remainder>` by calling itself, so host, port, and path keep the `https://` grammar
  and ADR 0026's host rule never applies. Any other scheme fails with a scheme message naming all
  three, a changed message for every other scheme. `_validate_origin`, which `--publish-url`
  shares, does not change.
- `assets/dracut/iso-chain-launch.sh`: `valid_source` gains an `ftp://*@*` arm calling new
  `valid_ftp_userinfo` and `valid_userinfo_part`; ADR 0026's check runs only for `http`.
  `download_artifact` is unchanged: curl fetches `"$source$2"` and a failure prints only
  `<label>-http: failed`.
- Tests in both suites, README, AGENTS.md, and the v4 spec's `source` bullet.

No ownership transition: validation stays in the two existing validators.
`compose_target_manifest` needs no change: it copies the base `source` through `_validate_source`.
`_kernel_arguments` already refuses a command line over 2,048 bytes, and `_grub_config`
single-quotes it; the admitted characters include no `'`, whitespace, `$`, or `\`.

Out of scope (owners): FTPS, anonymous FTP, HTTP fallback, a target-request `source` override
(operator); `validate-external-source` and the evidence verifiers (#69); the QEMU proof and
installer percent-decoding (#70); the runbook (#71); the PowerVM run (#37).

## Rule

A source starting `ftp://` is valid when, splitting the rest at its first `@`:

1. the part before it is `<user>:<password>` with exactly one `:`, both parts non-empty, each a
   run of `[A-Za-z0-9._~-]` or `%` plus two upper-case hex digits;
2. no escape is `%00`-`%1F` or `%7F`, or encodes `[A-Za-z0-9._~-]`; `%80`-`%FF` pass;
3. the userinfo is at most 128 bytes as written;
4. `https://` followed by the part after `@` passes today's `https://` source rule.

Python refusals, each naming the rule and no part of the URL:

- `manifest source: must use the canonical lower-case http://, https://, or ftp:// scheme`
- `manifest source: ftp:// needs <user>:<password>@ of unreserved characters and upper-case %XX escapes`
- `manifest source: ftp:// userinfo exceeds 128 bytes`
- `manifest source: ftp:// userinfo escapes must not encode a control or unreserved character`
- `manifest source: ftp:// host, port, and path must follow the https:// source grammar`

The launcher's `valid_source` returns 1, so `main` prints `configuration: failed` before any
network call.

## Success

1. `_validate_source` and `valid_source` agree on every member of one case table: the existing
   HTTP rows plus FTP rows covering each numbered rule's accept and refuse sides, `ftps://`,
   `FTP://`, and userinfo on `http://` and `https://`.
2. Loading a manifest with any refused FTP row raises one of the messages above, containing no
   user, password, or host from the row; `build` runs no external command for one.
3. A 128-byte userinfo manifest builds kernel arguments under 2,048 bytes and a GRUB variable
   holding the source unchanged inside single quotes.
4. An FTP base manifest composes with a target request and keeps its `source`.
5. `--publish-url` still refuses an `ftp://` URL and HTTP(S) userinfo.
6. The launcher test boots an FTP source through every pinned download, and a curl fault prints
   `kernel-http: failed` with no userinfo in the output.
7. `just check` exits 0.

## Validation

- Success 1: focused test `ManifestV4Tests.test_source_rule_matches_launcher`.
- Success 2: `ManifestV4Tests.test_rejects_ftp_source_without_echoing_it`,
  `BuildTests.test_refuses_ftp_source_before_any_command`.
- Success 3: `BuildTests.test_longest_ftp_userinfo_fits_command_line_and_grub_quoting`.
- Success 4: `TargetRequestTests.test_composes_ftp_base_source`.
- Success 5: `BuildTests.test_publish_url_stays_credential_free`.
- Success 6: `bash tests/test_iso_chain_launch.sh`.
- No emulator run: #70 owns the QEMU proof; the black-box test runs the real launcher script.

## Failure model

1. Actors and deployments: a local operator or hmcpctl running `build`; the launcher in a QEMU
   pSeries guest or a PowerVM partition; an FTP server on any host.
2. Invariants and assets: the credential reaches no refusal message or launcher failure marker;
   one rule in both layers; HTTP(S) and `--publish-url` behavior unchanged; artifact size and
   SHA-256 checks unchanged; the 2,048-byte command line.
3. Accepted failure classes:
   - the credential on the ISO, in `inspect` output, and on console captures of kernel and
     installer command lines: ADR 0016 and ADR 0027 consequences;
   - installer substitution of unpinned content over plain FTP: ADR 0027 accepted risk;
   - curl's own stderr on a failed transfer names the host, never the userinfo. verified:
     curl 8.18.0 (Fedora 44 x86_64) printed `curl: (67) Access denied: 530` for a refused login
     and `curl: (6) Could not resolve host: <host>` for `ftp://<user>:<password>@<host>/a/b`.
   - until #69, `validate-external-source` on an FTP manifest logs in through urllib's default
     FTP handler and fails with a fixed message that names no URL.
4. Covered elsewhere: `validate-external-source` over FTP (#69); installer decoding (#70).

### Threat model

- Boundaries: the manifest `source` widens to a credential-bearing scheme; no boundary is added.
- Actors: an on-path observer of FTP traffic; a reader of `build` or launcher error output. The
  operator who writes the manifest is trusted.
- Control: the rule above in both validators; refusals name only the rule; a failed transfer
  prints the fixed `<label>-http: failed` marker after curl's host-only stderr.
- Out of scope: credential exposure in transit and on media (ADR 0016, ADR 0027 accepted).
