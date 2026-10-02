# Target-Bound Installation Media

## Problem

hmcpctl provisions a partition, reads the client adapter's actual MAC, and then needs launcher media
bound to that MAC, the requested static network, one installer profile, and its own operation.
hmc-mcp ADR 0191 Decision 4 lets it run one operator-configured build entry: a fixed executable and
argument template in which only the manifest path varies, with no shell. It accepts the media only
when a versioned producer result, `iso-chain-media-v1`, equals its request (hmc-mcp spec
`2026-10-01-logical-lpar-workflows-design.md`, *Installation media and boot*).

Today `build` needs a complete manifest v4, including pinned source artifacts that hmcpctl does not
know, needs a fresh `--output` path per call, and prints nothing a caller can check.

Decision record: [ADR 0015](../../adr/0015-emit-a-target-bound-producer-result.md). Issue #23.

## Contract

### Target request

`build --target FILE --base-config FILE` replaces `--config FILE`; exactly one of the two forms is
given. The target request is at most 64 KiB of UTF-8 JSON with no duplicate keys and exactly these
fields, `operation_binding` optional:

```json
{
  "format": "iso-chain-target-v1",
  "profile": "ubuntu-26.04.1",
  "lpar": "sys-r1",
  "mac": "52:54:00:12:34:56",
  "network": {
    "address": "10.0.2.15/24",
    "routes": [{"destination": "0.0.0.0/0", "gateway": "10.0.2.2"}],
    "dns": ["10.0.2.3"]
  },
  "operation_binding": "00000000000000000000000000000001"
}
```

The base manifest is at most 64 KiB with exactly `version`, `source`, and `profiles`, in manifest
v4 grammar. `profile` is `<distribution>-<release>`, hmcpctl's `install.profile` form, and must
match exactly one base profile; base profile keys stay the operator's. `lpar` is a lower-case
identifier of at most 32 characters, used as the installer hostname; the writer derives it and the
result does not echo it. `build` composes a manifest v4 from `version`, `source`, the matched
profile alone under its base key, `selected_profile` equal to that key, `lpar`,
`network` with `mac` added, and `operation_binding` when present. It then validates the composite
with `load_manifest_bytes`, so every existing rule applies, including the Ubuntu and openSUSE
network subsets. The other base profiles are not on the ISO.

### Manifest v4

Manifest v4 gains one optional top-level field, `operation_binding`: exactly 32 lower-case hex
digits, hmcpctl's `operation_id` form (hmc-mcp ADR 0190). A manifest without it is unchanged and
keeps its digest. The launcher ignores it; it is bound only through `iso_chain.config_sha256`.

### Output and publication

Exactly one of `--output PATH` or the pair `--publish-dir DIR --publish-url URL` is given.
`--publish-url` must pass the manifest's `source` origin rules. The build is written beside its
destination, hashed once, and hard-linked with no replace to `--output` or to
`<publish-dir>/<iso_sha256>.iso`. An existing destination fails after the build, so an identical
rerun of a reproducible build fails rather than reporting the earlier file. The working directory
is a mode-0700 `.iso-chain-*` directory inside the publish directory, so the link stays on one
filesystem; an interrupted build can leave one behind. The file mode follows the build's umask.
Deleting published ISOs and leftover `.iso-chain-*` directories is the operator's.

`operation_binding` is present in the manifest exactly when the ISO is published: `build` refuses
a bound manifest with `--output` and an unbound one with `--publish-*`. Built mode is therefore a
bound, published ISO; prepared mode is an unbound ISO built with `--output`.

### Producer result

Every successful `build` prints one line of canonical JSON (sorted keys, no spaces, trailing
newline) on stdout; child tools' stdout goes to stderr. `inspect --result ISO` prints the same
object for an existing prepared ISO and refuses one whose manifest carries `operation_binding`.
Fields:

| Field | Value |
| --- | --- |
| `format` | `iso-chain-media-v1` |
| `iso_sha256`, `iso_size` | the ISO file's SHA-256 and byte size |
| `manifest_sha256` | the embedded canonical manifest's SHA-256 |
| `distribution`, `release` | the selected profile's |
| `architecture` | `ppc64le` |
| `mac` | `network.mac` |
| `network` | `address`, `routes` as `{destination, gateway}`, `dns`, in manifest order |
| `operation_binding` | built mode only |
| `url` | built mode only: `<publish-url>/<iso_sha256>.iso` |

A result over 64 KiB fails. `container-build` accepts the same inputs, mounts the target and base
directories read-only and the publish directory writable, and passes them to the inner `build`,
whose stdout is the container's. Before starting the engine it composes and validates the inputs
as `build` does, and it refuses a publish directory that is the filesystem or repository root, as
it does for `--output`'s directory.

### Errors

Invalid input raises `ValidationError` (exit 2) before any external command runs, naming the field
without echoing its value. Request fields that fill the composite are named as composite fields
(`manifest network.routes: ...`); request-only and base-shape errors name `target` or `base`.
The one post-build failure is an existing publish destination.

## Failure model

1. **Actors and deployments**
   - hmcpctl's server host running the configured build entry, unattended (built mode).
   - A local operator at a terminal on Linux or macOS (prepared mode and existing workflows).
2. **Invariants and assets at stake**
   - The result equals the bytes published: digest, size, manifest digest, network, MAC.
   - The ISO boots only the result's profile, MAC, and network.
   - No existing file is replaced; existing v4 manifests keep their digests.
3. **Accepted failure classes**
   - `inspect --result` hashes the ISO separately from extracting it; a file changed in between
     is the operator's own concurrent write.
   - Published ISOs and `.iso-chain-*` directories left by refused, retried, or interrupted
     builds; cleanup is the operator's (approved exclusion).
   - A plain-HTTP `--publish-url`; hmcpctl's allowlist governs which origins it accepts.
4. **Covered elsewhere**
   - Plain-HTTP restriction for origins: issue #29.
   - Request-to-result comparison and URL allowlist: hmcpctl (hmc-mcp#1215 children).
   - Disk safety and installed-disk boot: #24, #25.

## Threat model

1. **Boundary inventory**
   - Added: the target request file and `--publish-url`, from hmcpctl or the operator.
   - Added: writes into the publish directory, read later by the operator's HTTP server.
   - Widened: none; the base manifest has today's manifest trust.
2. **Actor model**
   - hmcpctl is trusted to run the entry but its request values come from MCP callers, so they
     are untrusted data. The operator owns the base manifest, directories, and URL.
3. **Control per boundary**
   - Target request: 64 KiB bound, duplicate-key and exact-field rejection, composite validation
     by the existing manifest parser; no value reaches a shell, and kernel arguments are built
     only from validated values.
   - Publish name: derived from a computed hex digest only; no-replace hard link; no symlink
     following on the destination.
   - Errors name fields, never values.
4. **Explicitly out of scope**
   - Serving, TLS, and access control of the publish directory: operator deployment.
   - SSH keys and login user: refused as unknown fields until #24/#25 add them, so hmcpctl's
     built mode, which forwards them, is refused until then; prepared and keyless use work now.

## Success

1. A target request plus a base manifest builds an ISO whose embedded manifest holds only the
   requested profile and whose result matches the table above.
2. `--publish-dir`/`--publish-url` publishes `<iso_sha256>.iso` and the result's `url` names it.
3. Existing `--config`/`--output` builds and manifests without `operation_binding` behave as
   before, apart from the result line on stdout.
4. Each input-validation rejection under *Errors* fails before any external command.
5. `inspect --result` reports a prepared ISO and refuses a bound one.
