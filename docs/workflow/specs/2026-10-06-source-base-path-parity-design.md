# Manifest Path Parity Design

Issue: #66.

## Problem

`URI_PATH` (`scripts/iso_chain.py`) allows `+` and `^`. The launcher's `valid_path`
(`assets/dracut/iso-chain-launch.sh`) refuses both for every path. `_validate_source` checks the
manifest `source` base path only with `URI_PATH`, and nothing there rejects `.` or `..` segments.
`_url_path` checks artifact, repository, Kickstart, and `live_iso` paths with the same pattern. So
`build` can produce an ISO whose launcher stops at boot with `configuration: failed`.

`URI_PATH` gained `+` and `^` (commit 4234bbe) so that `_access_records` would accept installer
package downloads, for example `gcc-c++` and `compsize-1.5^git…`. Those paths reach the
install-evidence verifiers through the HTTP access log. The launcher never fetches them.

## Scope

In scope:

- `scripts/iso_chain.py`
  - `URI_PATH` drops `+` and `^` and becomes the launcher's `valid_path` character set.
  - `ACCESS_LOG_PATH` keeps the wider set. `_url_path` takes a grammar argument, defaulting to
    `URI_PATH`, and `_access_records` passes `ACCESS_LOG_PATH`.
  - `_validate_source` refuses `.` and `..` base-path segments after `_validate_origin`.
- `tests/test_iso_chain.py`
  - The parity tables run against the launcher: source base paths through `valid_source`, and
    artifact and repository paths through `valid_path`.
  - A test that a refused artifact path's error does not echo it.
  - The package-path test now targets access-log records.

Out of scope (owners): authenticated FTP userinfo (#68); plain-HTTP host rules (ADR 0026);
hostname grammar (none).

The other `URI_PATH` callers narrow with it. `_validate_origin` serves `source` and
`--publish-url`. The `.treeinfo` check runs before kernel and initrd paths are pinned into a
manifest. `_url_path` also checks the `prepare-*-source` `--repository-path` and
`--release-path` arguments, which become manifest paths.

No ownership transition: every rule stays where it is now.

### Failure model

1. Actors: a local operator running `build`, `container-build`, `prepare-*-source`, or
   `validate-external-source`; the launcher in a QEMU or PowerVM guest; `verify-*-install-evidence`
   reading an access log.
2. Invariants:
   - Every manifest path `build` accepts is one the launcher accepts.
   - An access log of a real Fedora or Rocky install still verifies.
   - Errors name only the field.
3. Accepted failures, at `build` or `prepare-*-source` rather than at boot:
   - a private manifest, `.treeinfo`, `--publish-url`, `--repository-path`, or `--release-path`
     path that uses `+` or `^`;
   - a base path with a `.` or `..` segment.

   The launcher always refused these manifest paths, so no working media is lost.

## Success

1. `_validate_source` and the launcher's `valid_source` agree on every source case:
   - Accepted: `https://mirror.example/fedora/44`, `https://mirror.example/a.b/c~d_e-f`, and the
     near-miss dot segments `https://mirror.example/...` and `https://mirror.example/a..b/.c`.
   - Refused: `https://mirror.example/a+b`, `/a^b`, `/./a`, `/a/./b`, `/a/../b`, `/a/..`, `/..`.
2. `_url_path` and `valid_path` agree on every path case:
   - Accepted: `/fedora/44/os`, `/a.b/c~d_e-f`, `/...`, and `/a..b/.c`.
   - Refused: `/a+b`, `/a^b`, a `gcc-c++` package path, `/./a`, `/a/../b`, `/a/..`, `/`, `/a/`,
     `//a`, `a`, and `/a%2fb`.
3. Errors from refused paths:
   - A refused source fails with
     `manifest source: must be a canonical HTTP(S) origin or base path`.
   - A kernel path with `+` or `^` fails with
     `manifest profiles.fedora.kernel.path: must be a canonical absolute URL path`.
   - Neither message contains the path.
4. `_access_records` accepts the `compsize-1.5^git…` and `gcc-c++` package paths.
5. `just check` exits 0.

## Validation

- Success 1: focused-test `ManifestV4Tests.test_plain_http_source_rule_matches_launcher`.
- Success 2: focused-test `ManifestV4Tests.test_url_path_rule_matches_launcher`.
- Success 3: focused-tests
  - `ManifestV4Tests.test_rejects_noncanonical_source_base_path_without_echoing_it`
  - `ManifestV4Tests.test_rejects_launcher_refused_artifact_path_without_echoing_it`
- Success 4: focused-test
  `ManifestV4Tests.test_access_log_accepts_fedora_package_filename_characters`.
- Launcher: task-test-not-applicable. `valid_path` is unchanged, and both parity tests run it.
- Docs: none of the README, ADR 0006, ADR 0011, or the v4 spec states the `URI_PATH` character
  set. The Fedora profile spec says paths use "unreserved segments", which now holds.
