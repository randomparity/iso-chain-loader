# ADR 0015: Bind Targets Through a Request and Emit a Producer Result

## Status

Accepted

## Context

hmcpctl (hmc-mcp ADR 0191) builds media after it creates a partition and reads the adapter's
actual MAC. It runs one operator-configured build entry with a fixed argument template in which
only the manifest path varies, then refuses the media unless an `iso-chain-media-v1` result equals
its request. hmcpctl knows the profile name, partition name, MAC, network, and its 32-hex
`operation_id`. It does not know the pinned source artifacts that a manifest v4 carries; the
operator prepares those with the `prepare-*-source` commands. `build` today takes one complete
manifest, a fresh output path, and prints nothing.

## Decision

- **Input.** `build` and `container-build` accept `--target FILE --base-config FILE` as an
  alternative to `--config`. The target request (`iso-chain-target-v1`) carries the per-partition
  values; the operator's base manifest carries `version`, `source`, and `profiles`. `build` composes
  a manifest v4 holding only the requested profile and validates it with the existing parser.
- **Binding.** Manifest v4 gains an optional `operation_binding`. The version stays `4`, existing
  manifests keep their digests, and the binding is covered by `manifest_sha256`.
- **Publication.** `--publish-dir DIR --publish-url URL` replaces `--output` for built mode and
  publishes `<iso_sha256>.iso` with no replace. The operator deletes published files.
- **Result.** Every `build` prints one canonical `iso-chain-media-v1` JSON line on stdout;
  `inspect --result` prints it for existing media. `url` and `operation_binding` appear only when
  published and bound, respectively.

## Consequences

- One base manifest serves every partition; only the request file changes per call.
- `build`'s stdout is now the result, so child tools' stdout moves to stderr.
- SSH keys and the login user are unknown target fields until #24 and #25 add them.
- Published ISOs accumulate until the operator removes them.

## Considered & rejected

- **hmcpctl writes a complete manifest.** judgment: fit; hmcpctl would have to learn every
  profile's pinned digests, which the operator's preparation step owns.
- **Manifest v5, rejecting v4.** judgment: cost; every private manifest would need regenerating
  for one optional field.
- **Bind the operation in the result only.** judgment: fit; the ISO and its manifest digest would
  not show which operation it was built for.
- **Keep every base profile on the ISO.** judgment: fit; the console menu could boot an installer
  other than the one the result binds.
- **A separate producer command or media server.** judgment: fit; issue #23 asks to extend the
  existing `build` and `inspect` commands.
- **Name published files by operation.** judgment: fit; a digest name cannot collide with different
  content and needs no second identifier grammar.
- **An unpublish command.** judgment: fit; the operator declined it on 2026-10-02.
