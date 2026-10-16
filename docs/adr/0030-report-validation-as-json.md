# ADR 0030: Report validation as JSON

## Status

Proposed (2026-10-16); requires operator approval before implementation.

## Context

Issue #86 requires an opt-in versioned report for validate-config and seven verifiers while
preserving default streams/exits, evidence formats, private input safety and tool dependencies.
The existing parser/main boundary owns command selection and presentation.

## Decision

Add subcommand-local `--json` for those eight commands. Emit `iso-chain-report-v1` with command,
outcome, completed atomic checks and null or bounded category/field error metadata. Validation
success has configuration/renderability checks; verifier success has verification; failure has
no completed atomic checks. Use structured exception metadata rather than parsing prose.
Keep text mode and direct verifier return values. Preserve help as human text; JSON usage errors
use the same report envelope. The linked specification defines exact fields and failure exits.

## Consequences

Consumers can dispatch by command/version and category without private prose. Atomic reports
omit internal progress and do not strengthen evidence proof or operator assertions. Known schema
fields may be reported; dynamic fields are omitted. A narrow tcpdump exception subtype preserves
its existing validation exit while distinguishing tool failures. No evidence format changes.

## Considered & rejected

- **Do nothing.** judgment: leaves the requested machine-readable interface absent.
- **Replace default text with JSON.** judgment: breaks the explicitly protected default interface.
- **JSON progress events from each validator.** judgment: spreads reporting state through semantic
  code and creates a larger public contract than atomic completion requires.
- **Parse prose into error codes and field paths.** judgment: unstable and risks leaking input.
- **Repository-wide exception taxonomy.** judgment: exceeds this bounded reporting requirement.
