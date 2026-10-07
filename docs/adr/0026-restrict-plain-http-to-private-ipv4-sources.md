# ADR 0026: Restrict Plain-HTTP Sources to Loopback and Private IPv4 Addresses

## Status

Accepted

> **Amended by [ADR 0027](0027-accept-plain-ftp-sources-with-userinfo.md)** (2026-10-06): once #68
> implements it, a plain `ftp://` `source` is accepted for any host, an FTP-only exception, and
> accepts installer substitution on the routed path; plain `http://` keeps the rule below.

## Context

Under manifest v4 (ADR 0011) Anaconda fetches its stage2 `install.img` from `source` with no
digest; ADR 0011 accepts that risk on a trusted mirror. Over `http://` the runtime is also
unauthenticated in transit, so an on-path attacker can replace the installer. ADR 0007 kept plain
HTTP for "loopback or controlled test fixtures", and the v4 spec says `source` "uses HTTPS, or HTTP
for loopback and controlled test servers", but `_validate_source` and the launcher's
`valid_source` accept `http://` for any host. Issue #29 asks for enforcement.

Plain HTTP has three users that must keep working: `serve-source` on loopback for host-side
`validate-external-source`, QEMU user networking, where the guest reaches the host as `10.0.2.2`,
and lab installs on real partitions, which use plain HTTP on private networks (epic #1 goal 5).

## Decision

- **Rule.** An `https://` source keeps today's grammar for any host. An `http://` source is
  accepted only when its host is a canonical IPv4 literal in `127.0.0.0/8` (loopback) or an
  RFC 1918 range: `10.0.0.0/8`, `172.16.0.0/12`, or `192.168.0.0/16`. A DNS name, `localhost`
  included, needs `https://`.
- **Both layers.** `_validate_source` in `scripts/iso_chain.py` and `valid_source` in
  `assets/dracut/iso-chain-launch.sh` apply the identical rule after their existing grammar
  checks. `build` refuses such a manifest before any external command, and a launcher given one
  prints only `configuration: failed`.
- **Error.** `manifest <field>: plain http:// requires a loopback or RFC 1918 IPv4 address; use
  https:// for any other host`, which names no part of the input.
- **`--publish-url`.** Unaffected: it keeps today's grammar for any host. Its reader downloads the
  ISO and checks it against the `iso_sha256` in the `iso-chain-media-v1` result (ADR 0015; epic #1
  goal 7), so the bytes are authenticated whatever the transport, unlike `install.img`.
- **Version.** The manifest stays version `4`. No field is added or changed; a manifest whose
  `source` breaks the rule fails with the error above and is fixed by editing `source`.

## Consequences

- A v4 manifest with a plain-HTTP public host, or a plain-HTTP DNS name, that validated before now
  fails `build`, `validate-external-source`, and every command that loads it.
- The rule bounds plain HTTP to address space that is not routed on the internet; it does not
  authenticate a private network. An on-path attacker inside the lab network can still replace
  `install.img`, the risk ADR 0011 already accepts for a trusted mirror.
- A launcher initramfs built before this change does not enforce the rule, but `build` does, so a
  new ISO cannot carry a refused `source`.
- A lab mirror outside these ranges, on carrier-grade NAT space or another internal block, must
  serve `https://`; lab installs today use plain HTTP on RFC 1918 networks.

## Considered & rejected

- **Do nothing.** judgment: fit; the spec's stated contract and ADR 0007's intent stay unenforced.
- **Loopback and `10.0.2.2` only.** judgment: fit; lab installs on real partitions use plain HTTP on
  private networks, and epic #1 goal 5 requires them to keep working.
- **An opt-in manifest field or plain-HTTP host allowlist.** judgment: cost; it adds a manifest
  field and a kernel argument the launcher must parse, for networks the RFC 1918 rule already
  admits.
- **Apply the rule to `--publish-url` as well.** judgment: fit; the reader already authenticates
  the ISO by digest (epic #1 goal 7), so the rule would only refuse media hosts that reader admits.
- **Python's `IPv4Address.is_private`.** verified: `python3.14 -c "import ipaddress;
  print(ipaddress.IPv4Address('192.0.2.2').is_private, ipaddress.IPv4Address('198.18.0.1').is_private)"`
  prints `True True` (CPython 3.14), so documentation and benchmarking ranges would pass, and the
  launcher cannot reproduce the stdlib's table.
- **Allow DNS names that resolve to private addresses.** judgment: fit; `build` and the guest
  resolve with different resolvers at different times, so the check would not bind the fetch.
- **Bump the manifest version.** judgment: cost; nothing changes shape, and every compliant private
  manifest would need regenerating.
