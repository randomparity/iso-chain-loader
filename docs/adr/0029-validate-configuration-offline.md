# ADR 0029: Validate configuration offline

## Status

Accepted (2026-10-16), following explicit operator approval of the reviewed design.

## Context

Issue #83 requires checking a manifest, or a target request with its base manifest, before
preparing artifacts or invoking a builder. Existing parsing and unattended rendering already
express the content policy, but `_build_manifest` couples them to output/publication options.

## Decision

Add `validate-config --config PATH`, or `validate-config --target PATH --base-config PATH`.
Share input selection, parsing/composition, login compatibility and in-memory rendering with
build. Separately check the existing launcher argument bound for each carried profile.
The offline command accepts no artifact, output, publication, GRUB or container options.
Print a human report of completed checks and explicitly untested properties after success.
Keep build's output policy, ordering, result bytes and runtime behavior unchanged.

## Consequences

The command proves bounded content and local renderability, including built-in unattended
assets when needed. It cannot prove artifact existence/digests, reachability, a successful
build, or a boot/install. No composed manifest or rendered artifact is written.
Existing content rules have one owner; build retains its distinct output/publication owner.
JSON reporting belongs to #86 and does not change this default human interface.

## Considered & rejected

- **Do nothing.** judgment: leaves the explicitly requested offline check unavailable.
- **`validate-manifest`.** judgment: understates the supported target/base input mode.
- **`build --validate-only`.** judgment: mixes content validation with unrelated build options
  and makes its prerequisite boundary harder to explain.
- **Duplicate build checks.** judgment: risks divergent content policies for the two commands.
