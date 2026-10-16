# Contributor guidance and command checks

## Problem

Issue #87 identifies duplicated reference detail in AGENTS.md and a focused unittest command
naming the absent ManifestV3Tests. Contributor entry points need bounded executable evidence.

## Scope

One unit: shorten AGENTS.md to mandatory project invariants, commands, verification boundaries,
and a source/test/document map. Link README's task/prerequisite sections and existing ADRs/specs
for reference detail. Preserve target POWER9 ppc64le, no-fallback, digest/evidence, bounded-read,
no-replace/no-symlink, private-data, disk/completion and login restrictions; retain contributor
conventions and checks. Correct the focused command to ManifestV4Tests.

Extend the existing tests/test_iso_chain.py CLIHelpTests and unittest discovery, owned by
Justfile's check-tests and aggregate CI. Verify the literal documented focused command remains
present, then execute its fixed unittest arguments with the current Python interpreter; require
successful nonzero test execution. Document and check fixed top-level and build --help examples
in README's Development section, reusing the existing real CLI helper, empty PATH, temporary
working directory and timeout. Never execute text extracted from Markdown. No new recipe,
executor, runtime behavior, dependency or ownership transition is needed. No ADR is needed for
this extension of existing guidance and test ownership.

Exclusions approved by the operator on 2026-10-16: README navigation (#84), capability docs
(#83/#85/#86), FTP runbook (#71), RHEL (#78/#79), and a generic documentation executor.

### Failure model

- Prevent: missing/stale focused test targets and representative CLI help entry points.
- Detect: nonzero/zero-test unittest outcomes, failed help, unexpected stderr or local files.
- Accept: untested documentation shell blocks and environmental provisioning commands; this
  check is a fixed contributor smoke check, not proof that installer examples boot.
- Recover: fail the existing test gate with subprocess output; correct the documented entry point
  and its fixed check together. No network, build or destructive examples enter this check.

## Success

Guidance retains binding requirements with resolvable authoritative references; the selected
contributor commands work and are covered by existing local and CI discovery. No media proof
or future feature is claimed.

## Validation

- focused-test: CLIHelpTests gains documented command cases; red is the stale ManifestV3Tests
  reference or a controlled invalid help argument; green is `.venv/bin/python -m unittest -v
  tests.test_iso_chain.CLIHelpTests`. Prove both regressions fail before restoring the inputs.
- task-test-not-applicable: guidance organization and preserved normative prose require a manual
  before/after invariant and link review; prose snapshots would not establish semantic retention.
- Existing checks: focused lint/format/Markdown checks while iterating; final `just check` once
  tests and guidance are assembled. CI runs that same aggregate on macOS and Linux. Media and
  target execution are unchanged, so no QEMU or hardware run is warranted.
