# Offline configuration validation design

Issue #83, epic #81. Decision: [ADR 0029](../../adr/0029-validate-configuration-offline.md).
Authority: WORK:SCOPE q83-677f7a31; exact exclusions approved by the operator on 2026-10-16.
The operator approved this reviewed interface and ADR on 2026-10-16.

## Problem

Content validation currently requires build output options and local build prerequisites.
Operators and agents need an offline check before expensive preparation or execution.

## Contract

`python scripts/iso_chain.py validate-config --config PATH` accepts a complete manifest.
Alternatively use `--target PATH --base-config PATH`, composing only in memory through
`compose_target_manifest`. Exactly one input form is accepted. No positional inputs,
`--profile`, artifact, output, publication, GRUB or engine options are added.

Each input file uses the existing regular-file and 2 MiB bounded reader. Existing strict
JSON parsing, manifest v4 rules, source grammar, and target composition semantics apply.
The shared content path enforces profile/login compatibility and invokes the existing Rocky
or Ubuntu unattended renderer when keyed. The offline path calls `_kernel_arguments` for
each carried profile, selected or otherwise; its 2,048-byte limit includes the terminating
NUL. This creates no GRUB configuration. Bound manifests and multi-profile manifests are
accepted as content without publication constraints.

On success exit 0 and stdout contains three lines:

```text
configuration: passed (manifest content and profile/login compatibility)
renderability: passed (unattended content and launcher arguments for every carried profile)
not checked: artifact files/digests, source reachability, build, boot, install
```

No partial success report is printed. Validation failures exit 2 and emit `error: ...` only
on stderr. Preserve existing useful rule/field diagnostics, replacing profile map names in
`profiles.<name>` field paths with `<profile>` for this command. These validated identifiers
can still be private. Input paths, source credentials, login values, raw documents, rendered
content, digests and command lines are not echoed. Missing/unreadable inputs keep the existing
safe file errors. Built-in template read/decoding/JSON errors are translated to a fixed safe
validation error. Argparse help and usage errors retain its existing stream/exit behavior;
no JSON switch or error taxonomy is added. Templates are repository-owned trusted assets;
the command requires only Python and this checkout's assets, on supported development hosts.

## Ownership and compatibility

Move input selection into `_validate_configuration_args(args)` and the existing load,
compatibility and pre-render block into `_configuration_manifest(args)`; remove their old
copies. `_build_manifest` calls selection, output-option checks, content loading, then
publication policy in the current order. Its build and container-build callers remain.
Offline `validate_configuration(args)` calls selection/content loading and iterates arguments.
Only the offline wrapper sanitizes profile field paths and template exceptions. Build output,
publication, external dependencies, GRUB, staging, media producer/evidence formats and target
behavior remain unchanged. Existing renderers and argument construction remain their owners.

## Global constraints

Python 3.14; stdlib only in scripts/; 100-character lines; macOS arm64 and x86_64 Linux hosts;
ppc64le POWER9 media target. No runtime dependencies or toolchain-floor changes.
No network, subprocess invocation, output artifact, temporary directory or filesystem write
is performed by the offline validation implementation. It reads its declared JSON inputs and,
when rendering, the existing trusted unattended templates. Test harness fixture writes and
Python interpreter cache management are outside the command implementation's I/O contract.

## Failure model

1. Actors and deployments: local operators and agents invoking this CLI on supported hosts;
   CI running synthetic fixture inputs; operator-provided malformed or sensitive JSON.
2. Invariants/assets: exact content rules; bounded input reads; no external execution or
   output writes; private data excluded from reports; existing build behavior preserved.
3. Accepted failure classes: concurrent modification of input files after their bounded read
   does not invalidate this snapshot check; later build reads and verifies its own inputs.
   Arbitrarily corrupted trusted templates beyond read/encoding/JSON failure are covered by
   repository asset tests, rather than a new asset-schema validator.
4. Covered elsewhere: JSON/#86; examples/#85; README chooser/#84; artifact existence and
   digests/existing build and source verifiers; external execution and publication/existing
   prepare-build commands; boot-install proof/existing target workflows; composition output,
   new profiles, broad reorganization/separate approved scope.

## Threat model

- Added boundary: local JSON inputs enter the offline CLI. Widened boundaries: existing
  content policy and built-in template reads become available without build prerequisites.
- Actors: input authors may supply malformed/private values; repository templates are trusted.
- Controls: existing regular-file bounded readers, duplicate/strict JSON validation, fixed
  rule errors, offline profile-name redaction, safe template errors, no command/network/output
  APIs. Tests deny external boundaries and writes while validation runs.
- Out of scope: verifying source/artifact trust, hostile modification of this checkout or its
  Python runtime, installation proof, and concurrent post-validation input replacement.

## Success

1. Manifest and target/base modes pass supported Fedora, interactive Rocky/openSUSE/Ubuntu,
   keyed Rocky/Ubuntu, bound content, and compatible unkeyed multi-profile inputs.
2. The two declared input modes reject malformed, duplicate, oversized, unavailable and
   invalid-content JSON; keyed mixed/unsupported profiles and renderer failures are rejected.
3. The argument bound is checked for each carried profile, including an overlong unselected
   entry; exact boundary tests establish 2,048 bytes including NUL passes and 2,049 fails.
4. Synthetic success and failure CLI paths report only completed checks and omit private
   canaries. Focused denial tests prove no external calls or implementation output writes.
5. Existing build and container-build checks preserve validation order, publication policy,
   canonical content and generated GRUB/media behavior. `just check` passes.

## Validation

The matching transient implementation plan inventories executable contracts with focused
red/green tests and existing build regression classes. Human report/help/README prose is
reviewed for accuracy; tests observe exit/stream/privacy and argument acceptance, without
snapshotting prose. Run real CLI subprocesses on synthetic private fixtures with empty PATH
and PYTHONDONTWRITEBYTECODE=1. No media behavior changes; target boot/install proof is excluded.
