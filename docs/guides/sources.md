# Installer sources and pin validation

This guide covers the `source` URL rules every profile shares and the network check of a
profile's pinned files. Each distribution guide names its own pins and source tree.

## Source URL rules

An HTTP(S) `source` must be `https://`, or `http://` with a loopback or RFC 1918 IPv4 host such as
`127.0.0.1` or QEMU's `10.0.2.2` ([ADR
0026](../adr/0026-restrict-plain-http-to-private-ipv4-sources.md)); a DNS name, `localhost`
included, needs `https://`. `--publish-url` accepts either scheme for any host, with no credentials.
`source` may also be `ftp://<user>:<password>@<host>[:<port>][/<path>]` on any host ([ADR
0027](../adr/0027-accept-plain-ftp-sources-with-userinfo.md)): user and password are both required,
each made of `A-Z a-z 0-9 . _ ~ -` and upper-case `%XX` escapes, except `%00`-`%1F`, `%7F`, and an
escape of one of those listed characters such as `%41`; together they are at most 128 bytes as
written. Host, port, and path follow the `https://` grammar; `ftps://` and credentials in an
`http://` or `https://` `source` are refused, and no refusal names any part of the URL. The ISO, its
`inspect` output, and the kernel command lines carry the credential ([ADR
0016](../adr/0016-assess-authenticated-ftp-sources.md)). The launcher fetches its pinned files over
`ftp://`; whether each installer decodes an escape and how it resolves the path against the login
directory stay unproven until #70.

## Validate source pins

Before booting, check the origin without modifying it:

```sh
scripts/iso_chain.py validate-external-source --config MANIFEST \
  --profile PROFILE --timeout-seconds 30
```

For Fedora, Rocky and RHEL the command requests the four pinned files (kernel, initrd,
`.treeinfo`, and `repomd.xml`); for Ubuntu the kernel, initrd and live ISO; for openSUSE the
kernel and initrd. It
requires HTTP 200, the exact streamed byte count
(with either `Content-Length` or chunked responses), and the manifest's SHA-256. HTTPS uses the
system certificate and hostname checks; redirects, queries, fragments, and credentials in an
HTTP(S) `source` are rejected. An `ftp://` `source` is checked the same way apart from the HTTP
status: it logs in with the user and password decoded from their `%XX` escapes, which must form
UTF-8, and refuses before connecting otherwise or when the user holds `%3A`, an escaped `:` that
Python's `urllib` would move into the password. It ignores proxy variables such as `ftp_proxy`, and
fetches each file relative to the login directory. No refusal names the URL; a failed login reads
`external source request failed`. Mirror errors are not retried:
`dl.fedoraproject.org` has answered transient 404s, and a failed request fails the check, or the
boot, until it is run again. An opt-in test runs the same check when `ISO_CHAIN_EXTERNAL_MIRROR`
and `ISO_CHAIN_EXTERNAL_MANIFEST` are set; there is no implicit URL or fallback mirror.

## Serve a local tree

A QEMU run can serve a full copy of the repository itself with `serve-source`, which writes the
access log the evidence verifiers read; the command and its log format are in the
[installer smoke proof](verification.md#installer-smoke-proof). Each distribution guide lists the
paths its local tree needs.

## Authenticated FTP sources

Before adapting any profile sequence to an authenticated `ftp://` source, follow the [FTP operator
runbook](../ftp-operator-runbook.md) for account provisioning, evidence and cleanup. [ADR
0016](../adr/0016-assess-authenticated-ftp-sources.md) assesses the credential exposure and [ADR
0027](../adr/0027-accept-plain-ftp-sources-with-userinfo.md) defines the accepted URL form.

## Privacy and proof limits

Keep manifests, media, source trees, console logs, access logs, disk hashes and packet captures in
private storage (`umask 077`), using fresh output paths for every run, because they can contain
machine or network identifiers. Local checks and CI do not build or boot media. Emulator results
establish only their recorded QEMU boundary; native PowerVM requires separate proof.
