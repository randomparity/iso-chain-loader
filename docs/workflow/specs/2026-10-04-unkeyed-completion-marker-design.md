# Unkeyed Completion Marker Design

Issue: #62. Decision: [ADR 0025](../../adr/0025-keep-the-grubenv-only-rule-on-unkeyed-media.md),
following ADR 0018, 0020, and 0021.

## Problem

ADR 0021 requires `iso_chain_installed=1` only on keyed media, so an unkeyed ISO boots an
interrupted install's disk by default once its installer wrote `grubenv`. Issue #62 asks for a
recorded decision: (a) accept that consequence with a clearer rationale, or (b) require the marker
on unkeyed Fedora media, with implementation as follow-up work.

## Scope

- **Decision.** Option (a), recorded in ADR 0025: unkeyed media keeps ADR 0018's `grubenv`-only
  menu. No implementation follows, so no follow-up issue is needed.
- **Documents.** ADR 0025; a one-paragraph pointer to it in ADR 0021's `## Status`; README's
  installed-disk paragraph gains one sentence on the unkeyed consequence; AGENTS.md's ADR count
  and ADR list name 0025.
- No change to `scripts/`, `assets/`, `tests/`, the launcher, or any ISO's bytes.

## Failure model

1. **Actors and deployments**
   - A local operator building unkeyed media and reading the ADRs and README.
   - hmcpctl booting unkeyed media ISO-first on a PowerVM partition (hmc-mcp ADR 0191).
2. **Invariants and assets at stake**
   - Disks installed from unkeyed media keep their installed-disk default (ADR 0018).
   - The blank-disk guard still refuses to reinstall over a non-blank disk.
3. **Accepted failure classes**
   - An interrupted unkeyed install boots by default; bounded because the guard prevents overwrite
     and the operator zeros the disk to reinstall (ADR 0025 Consequences).
4. **Covered elsewhere**
   - Keyed-media marker: ADR 0021. Blank-disk guard changes: #60, #61.
   - Markers written by interactive installers: out of scope by operator decision.

## Success

1. ADR 0025 is Accepted, names option (a), and its Considered & rejected list includes option (b)
   with its compatibility cost for disks already installed from unkeyed Fedora media.
2. ADR 0021's body is unchanged apart from the Status pointer to ADR 0025.
3. README's installed-disk paragraph states the unkeyed consequence citing ADR 0025; AGENTS.md
   counts 25 ADRs and lists 0025.
4. `git diff --name-only main...HEAD` lists no path under `scripts/`, `assets/`, or `tests/`.

## Validation

- **Decision record (Success 1, 2, 3).** Mode: task-test-not-applicable; prose with no
  executable consumer, held by `just check`'s Markdown lint and review.
- **No behavior change (Success 4).** Mode: task-test-not-applicable; the diff touches no code or
  asset, so no test can fail; checked by the path list above.
