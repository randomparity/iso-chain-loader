# Unkeyed Completion Marker Implementation Plan

Goal: record that unkeyed media keeps ADR 0018's `grubenv`-only installed-disk rule. Spec:
`docs/workflow/specs/2026-10-04-unkeyed-completion-marker-design.md`; ADR 0025.

Architecture: documentation only. ADR 0025 holds the decision; ADR 0021, README, and AGENTS.md
point to it. No code, asset, or test changes.

Tech stack: Markdown, linted by rumdl through `just check`.

Expected implementation size: 8–14 changed lines (S) — a 3-line ADR 0021 Status pointer, a 2–3
line README sentence, and 3–4 AGENTS.md lines; the design artifacts are excluded.

## Global Constraints

- Markdown line length 100 (rumdl). `.secrets.baseline` covers no Markdown file.
- ADR 0021's body stays unchanged; only a quoted pointer is added under `## Status`, as ADR 0018's
  Status notes do.
- No path under `scripts/`, `assets/`, or `tests/` changes.

## File map

- `docs/adr/0021-require-a-completion-marker-on-keyed-media.md` — gains a Status pointer.
- `README.md` — the installed-disk paragraph beginning "The GRUB menu first searches".
- `AGENTS.md` — the `docs/adr/` count line and the `docs/adr/0024` list entry.

## Task 1: Point the documents at ADR 0025

Verification:

- **Pointers and count.** Mode: task-test-not-applicable; prose with no executable consumer;
  `just check-markdown` holds its form.
- **No behavior change.** Mode: task-test-not-applicable; no code path changes. Command:
  `git diff --name-only main...HEAD -- scripts assets tests`; expected: no output.

Steps:

1. In ADR 0021, after the `Accepted` line under `## Status`, add a blank line and:

   ```markdown
   > **Unkeyed media decided by [ADR 0025](0025-keep-the-grubenv-only-rule-on-unkeyed-media.md)**
   > (2026-10-04): the last Consequences bullet below is accepted as stated, with its rationale.
   ```

2. In README, after the sentence ending "which its unattended install writes last (ADR 0020,
   ADR 0021).", insert: "Any other ISO boots a disk whose install was interrupted after its
   installer wrote `grubenv`; zero the disk's first and last MiB to reinstall it (ADR 0025)."
   Reflow the paragraph to 100 columns.
3. In AGENTS.md, change "twenty-four accepted, binding ADRs (0001–0024)" to "twenty-five accepted,
   binding ADRs (0001–0025)", and after the `docs/adr/0024` entry add:

   ```markdown
   - `docs/adr/0025` — unkeyed media keeping ADR 0018's `grubenv`-only installed-disk rule.
   ```

4. Run `just check-markdown` (expect exit 0) and the no-behavior-change command (expect no
   output), then commit `docs: point ADR 0021, README, and AGENTS.md at ADR 0025`.

Acceptance: the three files name ADR 0025; `just check` exits 0.
