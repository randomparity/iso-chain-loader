# Plain-HTTP Source Restriction Design

Issue: #29 (epic #1). Decision: [ADR 0026](../../adr/0026-restrict-plain-http-to-private-ipv4-sources.md).

## Problem

`_validate_source` (`scripts/iso_chain.py`) and the launcher's `valid_source`
(`assets/dracut/iso-chain-launch.sh`) accept `http://` for any host, although Anaconda fetches
`install.img` from `source` with no digest, and the v4 contract limits HTTP to loopback and
controlled test servers.

## Scope

In scope:

- `scripts/iso_chain.py`: today's grammar moves to `_validate_origin`, which `--publish-url`
  (`build_iso`, `container_build_command`) now calls and which ADR 0026 leaves unrestricted;
  `_validate_source` calls it and then applies the rule against a `PLAIN_HTTP_NETWORKS` constant.
- `assets/dracut/iso-chain-launch.sh`: a `plain_http_host` function, called at the end of
  `valid_source` for an `http://` source.
- `tests/test_iso_chain.py`: manifest cases and one parity test that runs the launcher's
  `valid_source` against the same case table as `_validate_source`.
- `tests/test_iso_chain_launch.sh`: the fixture source moves from `http://192.0.2.2`, which the
  rule refuses, to `http://10.0.2.2`, the QEMU user-network host; one refusal case is added.
- Docs: ADR 0026; this spec; a dated Status note in ADR 0007 and ADR 0011 pointing at ADR 0026;
  the v4 spec, README, and AGENTS.md.

Out of scope (owners): authenticated FTP (#37); pinning `install.img` (ADR 0011 accepted risk);
HMC/VIOS orchestration (#6); a manifest version bump (ADR 0026 keeps version 4).

No ownership transition: validation stays in the two existing validators. The grammar moves to
`_validate_origin` and both `--publish-url` callers repoint to it, so their behavior is unchanged.

## Rule

After the existing grammar checks, an `http://` source passes only when its host is a canonical
dotted-quad IPv4 literal whose first octet is `127` or `10`, or whose first two octets are `192.168`
or `172.16` through `172.31`. `https://` is unchanged. A host that is not a canonical dotted
quad, such as `010.0.2.2`, passes both layers' grammar as a DNS name and is refused over `http://`.

Python raises `ValidationError("manifest <field>: plain http:// requires a loopback or RFC 1918
IPv4 address; use https:// for any other host")`. The launcher's `valid_source` returns 1, so
`main` prints `configuration: failed` and exits 1 before any network call.

## Success

1. `_validate_source` and `valid_source` accept and refuse exactly the same members of one shared
   case table in `tests/test_iso_chain.py`: every `https://` case, `http://` on `127.0.0.1`,
   `10.0.2.2`, `172.16.0.1`, `172.31.255.254`, `192.168.1.10` (accepted), and `http://` on
   `172.15.0.1`, `172.32.0.1`, `192.0.2.2`, `11.0.0.1`, `192.169.0.1`, `010.0.2.2`,
   `mirror.example`, `localhost` (refused).
2. A manifest with a refused `source` fails with the error above, the message does not contain
   the host, and no external command runs; `build` still accepts `--publish-url
   http://media.example/iso`.
3. The launcher black-box test still passes every existing case on `http://10.0.2.2`, and a
   refused plain-HTTP source prints `configuration: failed` with no network call.
4. `just check` exits 0.

## Validation

- Success 1: focused test, `ManifestV4Tests.test_plain_http_source_rule_matches_launcher`.
- Success 2: focused tests in `ManifestV4Tests`, `BuildTests`, and `ContainerBuildTests`.
- Success 3: `bash tests/test_iso_chain_launch.sh`.
- No emulator run: the change is argument validation the black-box test runs on the real launcher
  script; no runtime tool, kernel argument, or boot step changes.

## Failure model

1. Actors and deployments: a local operator running `build`, `validate-external-source`, or
   `container-build`; the launcher in a QEMU pSeries guest or a PowerVM partition; hmcpctl calling
   `build --target --publish-url`.
2. Invariants and assets: no new manifest or ISO carries a plain-HTTP source outside the allowance;
   the identical rule in both layers; QEMU user-net, loopback, and private-network lab sources keep
   working; errors never echo the input.
3. Accepted failure classes:
   - an on-path attacker inside a private network — ADR 0026 consequence, ADR 0011 trust in the
     mirror;
   - an old initramfs not enforcing the rule — `build` refuses the manifest first;
   - private manifests that used plain HTTP to a public host or DNS name now fail — the intended
     contract change, with an actionable error.
4. Covered elsewhere: FTP transport (#37); stage2 digest (ADR 0011).

### Threat model

- Boundaries: none added; the existing `source` input narrows; `--publish-url` is unchanged.
- Actors: an on-path network attacker between partition and mirror; the operator is trusted.
- Control: the rule above in both validators; failure leaks only the field name.
- Out of scope: attackers on the private install network; DNS spoofing of an `https://` host
  (TLS verification in Anaconda and the launcher's curl holds it; casper's unverified live-ISO
  fetch is ADR 0012's accepted risk).
