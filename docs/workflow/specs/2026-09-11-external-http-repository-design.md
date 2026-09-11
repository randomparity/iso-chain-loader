# External HTTP(S) repository validation

## Scope

Issue 19 adds a read-only preflight for an independently hosted Fedora or Red
Hat repository. Public origins use `https://`; `http://` remains available for
local and test servers. The existing local-server installation and JSONL proof
remain the deterministic path.

## Contract

`validate-external-source --config MANIFEST [--profile NAME]
[--timeout-seconds N]` loads and canonicalizes the version-3 manifest, selects
the named profile (or the manifest default), and requests each declared
launcher artifact: kernel, initramfs, `.treeinfo`, `repodata/repomd.xml`, and
Kickstart. It joins each manifest path to the origin without accepting a
query, fragment, credentials, redirects, or path traversal. Every response
must be HTTP 200, have the declared byte count (whether transferred with a
`Content-Length` header or chunked encoding), and match the declared SHA-256.
TLS uses Python's default certificate and hostname verification. The
command emits one JSON object per artifact and exits non-zero on any failure;
it never writes to the origin.

The command does not claim that arbitrary repository payloads were exhaustively
validated: the installer may request additional paths after the launcher
artifacts. Standard web-server access logs therefore satisfy runtime
corroboration only when adapted to the existing JSONL path/size contract; the
bundled server remains the stronger reproducible evidence source.

## Testing

Unit/integration tests use a local threaded HTTPS-capable test server with
deterministic files and cover success, size mismatch, digest mismatch, redirect
rejection, and HTTPS URL acceptance. A separate opt-in test reads
`ISO_CHAIN_EXTERNAL_MIRROR`; it has no default or fallback URL and is skipped
when unset. The ppc64le VM runs the command against an explicitly supplied
mirror or records that the opt-in arm was unavailable.
