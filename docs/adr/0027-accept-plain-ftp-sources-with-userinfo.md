# ADR 0027: Accept Plain FTP Sources with Bounded Userinfo

## Status

Accepted

## Context

ADR 0016 decides that an FTP credential travels as userinfo in the manifest `source`, on the ISO
and on the launcher and installer kernel command lines, and that nothing accepts an FTP source
until #37 implements it with the operator's approval. It left open the questions any code must
answer first (issue #67):

- **Approval.** #37 Expected item 1 requires the operator's explicit approval to implement FTP
  sources at all.
- **Characters.** Only `secrets.token_urlsafe` passwords were tested
  ([the FTP experiment](../experiments/2026-10-02-authenticated-ftp-sources.md)).
  `_validate_origin` in `scripts/iso_chain.py` rejects userinfo and the characters `\ " ' ? #` and
  whitespace, and `_grub_config` single-quotes each profile's arguments, so a `'` in a password
  would break GRUB quoting.
- **Host policy.** ADR 0026 restricts plain `http://` to loopback and RFC 1918 IPv4 hosts, and
  `AGENTS.md` states that public origins require HTTPS. Plain FTP is unauthenticated in transit
  and carries a clear-text credential as well.
- **FTPS.** ADR 0016 prefers `ftps://`, but none of the four installers accepted it in the
  experiment record, and the launcher's `curl --cacert` bundle rejects a private CA.
- **Base manifest.** `compose_target_manifest` takes `source` from the single operator base
  manifest of ADR 0015, which a per-run FTP account makes per-run.
- **Length.** The launcher command line is capped at 2,048 bytes (`MAX_COMMAND_LINE_BYTES`), and
  each GRUB menu entry must stay under the 1,024 bytes Fedora's GRUB can replay after a PowerVM
  CAS reboot.

## Decision

- **Approval.** On 2026-10-06 the operator approved implementing `ftp://` sources under #37.
- **Grammar.** A manifest `source` may be
  `ftp://<user>:<password>@<host>[:<port>]/<path>`. Both `<user>` and `<password>` are required
  and non-empty; there is no anonymous form and no user without a password. `<host>`, `<port>`,
  and `<path>` keep the grammar an `https://` `source` has today, including the launcher's path
  rules; query strings and fragments stay refused.
- **Userinfo characters.** `<user>` and `<password>` consist of RFC 3986 unreserved characters,
  `[A-Za-z0-9._~-]`, and percent-encoded octets, `%` followed by two hexadecimal digits. An escape
  that decodes to a control character, `%00` through `%1F` or `%7F`, is refused. No other
  character is admitted, so neither `'` nor whitespace can reach GRUB, the launcher's shell, or
  an installer argument.
- **Length.** The encoded `<user>:<password>` userinfo is at most 128 bytes, counted as written in
  the manifest, before any decoding.
- **Host policy.** A plain `ftp://` `source` is accepted for any host the `https://` grammar
  admits. This is an FTP-only exception to ADR 0026's loopback and RFC 1918 rule and to the
  "public origins require HTTPS" invariant; plain `http://` keeps ADR 0026's rule unchanged. The
  lab owner's written acceptance of clear-text credentials, which ADR 0016 requires for plain FTP,
  was given on 2026-10-06. It is recorded here by date only; the record names no person.
- **FTPS refused.** A `source` with the `ftps://` scheme is refused, because no installer accepts
  it. This amends ADR 0016's "FTPS preferred" by reference.
- **Userinfo stays FTP-only.** An `http://` or `https://` `source` with userinfo stays refused.
  `--publish-url`, which shares `_validate_origin` with `source`, does not widen: it stays a
  credential-free HTTP(S) URL.
- **Per-run base manifest.** For an FTP `source`, the operator's ADR 0015 base manifest is
  per-run, carrying that run's account. A target request gains no `source` override. This amends
  ADR 0015's "one base manifest serves every partition" by reference for FTP sources.
- **Errors name no input.** Every refusal of an FTP `source` names the rule broken and none of
  the URL, so no part of the credential reaches stderr.
- **Version.** The manifest stays version `4`; no field is added. A `source` that `build` refused
  before is the only one whose meaning changes.

## Consequences

- #68 implements the grammar in `build` and the launcher, and #69 in `validate-external-source`
  and the verifiers. Until #68 lands, `README.md` and `AGENTS.md` still say authenticated FTP
  sources are not accepted; #68 changes that sentence with the implementation.
- The 128-byte cap bounds what userinfo adds to the shared `iso_chain_args_<n>` line; #68 shows
  in a test that a maximum-length userinfo keeps the 2,048-byte command line and the 1,024-byte
  GRUB entry limits.
- Percent-encoded passwords are untested at the installers: the experiment used URL-safe passwords
  only. Whether each installer decodes an escape before logging in is open until #37's live run.
- A built FTP ISO, its published copy, and every console capture of its run carry a usable
  credential, as ADR 0016 records. On a public host the account is exposed to any on-path
  observer for its lifetime, so revocation after the run, ADR 0016's backstop, is what bounds it.
- Content fetched over plain FTP is unauthenticated in transit, as with plain HTTP under ADR
  0026; the pinned digests still cover every artifact the launcher downloads, and Anaconda's
  stage2 keeps the trusted-mirror risk ADR 0011 accepts.
- `hmcpctl`'s fixed build entry must point at a fresh base manifest for each FTP run; nothing in
  this repository creates or deletes it.

Out of scope, by operator decision on 2026-10-06: FTPS at the installers, anonymous FTP or any
HTTP fallback, an off-command-line credential channel, and account provisioning stay the
operator's; VIOS locking stays with #1; the PowerVM live run stays with #37.

## Considered & rejected

- **Unreserved characters only, no percent-encoding.** judgment: fit; the operator chose to admit
  percent-encoding on 2026-10-06 so an account's password need not be regenerated into the
  unreserved set, and the escape adds no character GRUB or the launcher's shell interprets.
- **Admit every escape, control characters included.** judgment: fit; a decoded control character
  could end or split a log line or an installer argument, and no password needs one.
- **ADR 0026's loopback and RFC 1918 rule for plain FTP.** judgment: fit; the operator chose any
  host on 2026-10-06, relying on the per-run account and its revocation rather than the network's
  address space.
- **Accept `ftps://` at the launcher only, with a carried trust anchor.** judgment: fit; no
  installer accepts `ftps://`, so the launcher would fetch over TLS and hand the installer a URL it
  cannot use.
- **A target-request `source` override.** judgment: fit; it would add a field to
  `iso-chain-target-v1` that hmcpctl must learn and carry a credential, which the operator chose
  to keep in the base manifest on 2026-10-06.
- **Refuse `--target` for FTP sources.** judgment: fit; hmcpctl builds only through `--target`, so
  FTP sources would be unusable from it.
- **A cap derived from the remaining command-line budget.** judgment: cost; the remaining budget
  varies with every profile's paths, so an operator could not know the limit before `build`.

Issue: [#67](https://github.com/randomparity/iso-chain-loader/issues/67), part of
[#37](https://github.com/randomparity/iso-chain-loader/issues/37).
