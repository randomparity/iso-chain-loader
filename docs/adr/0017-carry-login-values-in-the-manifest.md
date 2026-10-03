# ADR 0017: Carry SSH Keys and the Login User in the Manifest

## Status

Accepted

## Context

hmcpctl's built mode forwards 1 to 16 SSH public keys, each one printable line of up to 8,192
characters, and a login user matching `[a-z_][a-z0-9_-]{0,31}` (randomparity/hmc-mcp
`src/hmcpctl/operations/lpar/plan.py`). The unattended Rocky (#25) and Ubuntu (#24) installs must
apply them, but the `iso-chain-target-v1` request refuses both as unknown fields (ADR 0015), and
nothing decides how they reach an installer. The kernel command line is capped at 2,048 bytes, while
sixteen keys can exceed 128 KiB. The launcher runs in a dracut initramfs whose tools are `sh`,
`curl`, `sha256sum`, `cat`, and similar: it has no JSON parser. It already mounts the one optical
device whose `/iso-chain/config.json` matches `iso_chain.config_sha256`, and it checks each
media-carried Kickstart by size and SHA-256 before handing off.

## Decision

- **Manifest fields.** Manifest v4 gains two optional top-level fields, `ssh_authorized_keys` (an
  array of 1 to 16 strings, each 1 to 8,192 characters for which Python's `str.isprintable()` holds)
  and `login_user` (a string that fully matches `[a-z_][a-z0-9_-]{0,31}`). They appear together or
  not at all. The version stays `4`, and a manifest without them keeps its canonical bytes and
  digest. The target request accepts the same two fields and copies them into the composed manifest.
- **Carriage.** The values travel only in the canonical manifest, which `build` already writes to
  the launcher ISO as `/iso-chain/config.json` and which `iso_chain.config_sha256` binds. They never
  appear on the kernel command line or in the `iso-chain-media-v1` result. The manifest read bound
  grows from 64 KiB to 2 MiB, because sixteen maximum-length keys written with `\u` escapes, as
  Python's default `json.dumps` writes non-ASCII text, can occupy 1.5 MiB.
- **Consumption.** A profile that applies the values renders its installer input in `build`, on the
  host, from the parsed manifest's two fields and nothing else. It stages the rendered file on the
  launcher ISO, and the launcher checks that file by size and SHA-256 from the command line before
  handoff, as it checks a Kickstart. The file's form and how the installer reads it belong to the
  profile: Kickstart `user` and `sshkey` for Rocky (#25), autoinstall user data for Ubuntu (#24).
- **No silent drop.** Until a profile renders them, `build` and `container-build` refuse a manifest
  carrying the values before any external command runs, rather than producing media whose installer
  ignores them.

## Consequences

- One manifest digest binds the keys, the user, the network, and the profile pins, so #24 and #25
  share one validated source and add no request or manifest grammar.
- Today no profile applies the values, so hmcpctl's built mode is still refused, now at `build`
  rather than at request validation. Each profile's issue lifts the refusal for that profile alone.
- The values are public keys and an account name, not secrets: a private key spans several lines
  and fails the one-line rule. They are still identifiers, readable by anyone who can read the
  published ISO, so the publish directory's access control from ADR 0015 governs them.
- A rendered file adds one size and one digest argument to the command line, not the keys.
- The larger read bound also applies to `--config` manifests, the embedded manifest that `inspect`
  extracts, and the manifest given to `verify-fedora-install-evidence`.

## Considered & rejected

- **Put the values on the kernel command line.** verified: `_kernel_arguments` refuses a command
  line over `MAX_COMMAND_LINE_BYTES = 2048` (`scripts/iso_chain.py`, 3e5298b), and one
  maximum-length key alone is 8,192 bytes.
- **Have the launcher parse `config.json` in the guest.** verified: `DRACUT_TOOLS` in
  `scripts/iso_chain.py` (3e5298b) installs no JSON parser; adding `jq` or Python grows the
  initramfs and its parser surface for work the host already does.
- **A separate keys file beside the manifest.** judgment: fit; a second file needs its own digest
  binding, which the manifest already provides.
- **Put the values in the operator's base profile or Kickstart.** judgment: fit; the base is shared
  across partitions, while keys and the user arrive per request.
- **Accept the values and let interactive installers ignore them.** judgment: fit; it contradicts
  the repository's no-fallback rule, since a request for key-based access would yield media that
  silently omits it.
- **Restrict keys to ASCII to keep the 64 KiB bound.** judgment: fit; it narrows hmcpctl's bounds,
  so a request hmcpctl accepts would fail here, and sixteen ASCII keys still exceed 64 KiB.
- **Manifest v5.** judgment: cost; every private manifest would need regenerating for two optional
  fields, as ADR 0015 found for `operation_binding`.
- **Do nothing.** judgment: fit; #24 and #25 are blocked on this decision, and each would otherwise
  invent its own carriage.
