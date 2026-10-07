# ADR 0015: Bind Targets Through a Request and Emit a Producer Result

## Status

Accepted

> **Amended by [ADR 0027](0027-accept-plain-ftp-sources-with-userinfo.md)** (2026-10-06): once #68
> accepts `ftp://` sources, an FTP `source`'s base manifest is per-run, carrying that run's account,
> and a target request gains no `source` override; "one base manifest serves every partition" below
> holds for other sources.

## Context

hmcpctl (hmc-mcp ADR 0191) builds media after it creates a partition and reads the adapter's
actual MAC. It runs one operator-configured build entry with a fixed argument template in which
only the manifest path varies, then refuses the media unless an `iso-chain-media-v1` result equals
its request. hmcpctl knows the profile as `<distribution>-<release>`, the partition name, MAC,
network, and its 32-hex `operation_id`. It does not know the pinned source artifacts that a
manifest v4 carries; the operator prepares those with the `prepare-*-source` commands. `build`
today takes one complete manifest, a fresh output path, and prints nothing. ADR 0191 names no
result channel beyond "returns its URL", and the hmc-mcp spec's threat model calls the result a
"producer result file" bounded at 64 KiB. A per-call result file path would be a second varying
argument, so the result goes to stdout under the same bound; hmcpctl's build-entry runner
(hmc-mcp#1215 children) must read stdout, or the hmc-mcp spec must be amended to match.

## Decision

- **Input.** `build` and `container-build` accept `--target FILE --base-config FILE` as an
  alternative to `--config`. The target request (`iso-chain-target-v1`) carries the per-partition
  values and selects the one base profile whose distribution and release it names; the operator's
  base manifest carries `version`, `source`, and `profiles`. `build` composes a manifest v4
  holding only that profile and validates it with the existing parser.
- **Binding.** Manifest v4 gains an optional `operation_binding`. The version stays `4`, existing
  manifests keep their digests, and the binding is covered by `manifest_sha256`. A manifest is
  bound exactly when its ISO is published, so built and prepared media cannot mix.
- **Publication.** `--publish-dir DIR --publish-url URL` replaces `--output` for built mode and
  publishes `<iso_sha256>.iso` with no replace. The operator deletes published files.
- **Result.** Every `build` of a one-profile ISO prints one canonical `iso-chain-media-v1` JSON
  line on stdout; a multi-profile `--config` build prints none. `inspect --result` prints it for
  one-profile prepared media and refuses bound media. `url` and `operation_binding` appear only
  in built mode.

## Consequences

- One base manifest serves every partition; only the request file changes per call.
- `build`'s stdout is now the result, so child tools' stdout moves to stderr.
- SSH keys and the login user are accepted target and manifest fields (ADR 0017), but `build`
  refuses them until #24 and #25 apply them, so hmcpctl's built mode, which forwards them, is
  refused until then; prepared and keyless use work now.
- Published ISOs, and working directories of interrupted builds, accumulate until the operator
  removes them. The build is not byte-reproducible, so every retry publishes another ISO.

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
- **Select the profile by base key.** judgment: fit; hmcpctl holds `rocky-9.8`, which is not a
  manifest identifier, and cannot know the operator's key names.
- **Name published files by operation.** judgment: fit; a digest name cannot collide with different
  content and needs no second identifier grammar.
- **An unpublish command.** judgment: fit; the operator declined it on 2026-10-02.
