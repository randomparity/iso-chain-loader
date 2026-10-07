# FTP Source Checks Design

Issue: #69 (epic #37). Decision: [ADR 0027](../../adr/0027-accept-plain-ftp-sources-with-userinfo.md).

## Problem

`build` and the launcher accept an `ftp://<user>:<password>@...` `source` (#68), but
`validate_external_source` in `scripts/iso_chain.py` is HTTP-shaped: urllib's FTP response has
`status` `None`, so every FTP artifact fails `external source returned a non-200 response` after
a login. The evidence verifiers compare handoff URLs as strings, so FTP userinfo must neither
break them nor reach a refusal message.

## Scope

`validate_external_source` fetches an FTP source's pinned artifacts (option (a) of the issue):

- `ftp = manifest.source.startswith("ftp://")`. For FTP the opener is
  `build_opener(ProxyHandler({}), _NoRedirectHandler)`: an `ftp_proxy` variable would receive
  the credential over plain HTTP, and the project has no alternate path. HTTP(S) keeps today's
  opener, proxy behaviour included.
- Before any network call, the userinfo's escapes must decode as UTF-8
  (`unquote_to_bytes(...).decode("utf-8")`), because urllib's FTP handler decodes the user and
  password as UTF-8 with replacement and ftplib sends them as UTF-8. Refusal:
  `ftp:// userinfo escapes must decode as UTF-8 to check the source`.
- The `status != 200` check applies only to HTTP(S). Size, SHA-256, the per-artifact deadline,
  `_set_response_timeout`, the urllib `timeout` (ftplib's socket timeout), and the caught errors
  (urllib wraps every ftplib error in `URLError`) apply to FTP as they are. FTP has no redirect.

Verifiers: no code change. `iso_chain.source=`, `inst.repo=`, `iso-url=`, and `install=` are
compared as whole strings, and every refusal message is a fixed string. Tests prove both.
`verify-log` and `verify-pcap` read no manifest and no source, so they are not exercised.

No ownership transition: the FTP branch lives in the one function that owns the check.

README: replace the "until #69" sentence with the FTP behaviour, the UTF-8 rule, and the absent
proxy. AGENTS.md: drop "#69 owns `validate-external-source` and the verifiers".

### Failure model

1. Actors and deployments: the local operator running `validate-external-source` against a lab
   or public FTP server; CI running unit tests with no network.
2. Invariants: the user and password never appear on stdout or stderr; an artifact passes only
   with the manifest's exact size and SHA-256; the check fails rather than falls back.
3. Accepted: a password whose escapes are not UTF-8 cannot be checked here (refused before
   network; the launcher still fetches it); urllib's `550` fallback to a directory listing
   (bounded by size and refused by digest); a refusal raised mid-transfer returning up to one more
   `timeout_seconds` late, because urllib's close hook waits for the server's final reply;
   clear-text credential on the wire (ADR 0027).
4. Covered elsewhere: live FTP and installer behaviour (#70); FTPS (operator); a real FTP server
   in tests (operator); the HTTP(S) proxy behaviour (unchanged, outside #69); the installer and
   install-evidence verifiers still require a `serve-source` HTTP access log, which a real FTP run
   cannot produce, until new evidence fields are decided (operator) or #70.

### Threat model

- Boundaries: added — the host connects to an FTP server and sends the credential; widened —
  none. Server replies and data enter from that server.
- Actors: the FTP server and any on-path observer (untrusted); the operator who wrote the
  manifest (trusted).
- Controls: fixed messages for every failure; size cap while streaming; digest match; deadline
  and socket timeout; proxies disabled for FTP; no redirect.
- Out of scope: on-path credential capture (ADR 0027 accepted risk; revocation bounds it).

## Success

1. A mocked FTP boundary (`urllib.request.ftpwrapper`) returns the four Fedora artifacts and the
   three Ubuntu artifacts; `validate_external_source` returns their paths, sizes, and digests,
   and the wrapper receives the decoded user and password, the login-relative directories, and
   the timeout.
2. With `ftp_proxy` set, the FTP branch still calls the wrapper directly.
3. Each refusal — login failure (`ftplib.error_perm`), short read, oversize, digest mismatch,
   non-UTF-8 escape — raises its fixed message, and through `main`
   neither stdout nor stderr contains the user or the password.
4. Each existing evidence test class (`EvidenceTests`, `InstallerEvidenceTests`,
   `UbuntuEvidenceTests`, `RockyEvidenceTests`, `OpenSUSEEvidenceTests`,
   `FedoraInstallEvidenceTests`, `RockyInstallEvidenceTests`, `UbuntuInstallEvidenceTests`)
   passes again with an FTP source, and each refusal it asserts carries neither credential part.
5. `just check` exits 0.

## Validation

- `focused-test` for 1–3: new `ExternalFTPSourceTests` cases; red before the change because the
  FTP response's status is `None`.
- `focused-test` for 4: FTP subclasses of the eight classes; green on arrival (behaviour already
  holds), proved to bite by a temporary fault appending `manifest.source` to one verifier
  refusal message and seeing the no-echo assertion fail.
- `task-test-not-applicable` for README and AGENTS.md: prose with no executable consumer.
