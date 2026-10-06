# Source Base-Path Parity Design

Issue: #66.

## Problem

`_validate_source` (`scripts/iso_chain.py`) checks the manifest `source` base path only with
`URI_PATH`. That pattern allows `+` and `^`, and nothing rejects `.` or `..` segments. The
launcher's `valid_path` (`assets/dracut/iso-chain-launch.sh`) refuses all four, so `build`
produces an ISO whose launcher stops at boot with `configuration: failed`.

## Scope

In scope:

- `scripts/iso_chain.py`: after `_validate_origin`, `_validate_source` refuses a base path that
  holds `+`, `^`, or a `.` or `..` segment. One rule for `+` and `^`, refused in both layers, so the
  launcher and the documented character set stay as they are and no doc or ADR changes.
- `tests/test_iso_chain.py`: base-path cases in the shared parity tables.

Out of scope (owners): the artifact-path grammar `_url_path`, which shares `URI_PATH` and so
still admits `+`/`^` (none; reported as a follow-up candidate); authenticated FTP userinfo
(#68); plain-HTTP host rules (ADR 0026); hostname grammar (none); `--publish-url`, which uses
`_validate_origin` and is never fetched by the launcher (unchanged).

No ownership transition: the check stays in `_validate_source`, its only manifest caller.

### Failure model

1. Actors: a local operator running `build`, `container-build`, or `validate-external-source`;
   the launcher in a QEMU or PowerVM guest.
2. Invariants: every manifest `source` that `build` accepts is one the launcher accepts. Errors
   name only the field.
3. Accepted failure: a private manifest whose base path uses `+`, `^`, `.`, or `..` now fails at
   `build`, not at boot. The launcher always refused it, so no working media is lost.

## Success

1. `_validate_source` and the launcher's `valid_source` agree on every case in the parity tables.
   Accepted: `https://mirror.example/fedora/44`, `https://mirror.example/a.b/c~d_e-f`.
   Refused: `https://mirror.example/a+b`, `/a^b`, `/./a`, `/a/./b`, `/a/../b`, `/a/..`, `/..`.
2. A manifest with one of those refused sources fails with
   `manifest source: must be a canonical HTTP(S) origin or base path`. The message does not
   contain the path.
3. `just check` exits 0.

## Validation

- Success 1: focused-test `ManifestV4Tests.test_plain_http_source_rule_matches_launcher`.
- Success 2: focused-test `ManifestV4Tests.test_rejects_noncanonical_source_base_path`.
- Launcher: task-test-not-applicable. `valid_path` is unchanged, and the parity test already
  runs it.
