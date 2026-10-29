# Task-focused README and operator guides

## Problem

Issue #121 (part of epic #120): `README.md` is 1,206 lines that mix a quickstart, the operator
manual, contract restatements and experiment history. Generic steps (source-pin validation,
build, smoke proof) sit under the Fedora section although every profile uses them, and no
table states each distribution's modes, memory floor, trust anchor, example file and proof
status. This change reorganises prose only. No contract, safety rule, command, flag, limit or
proof boundary changes.

## Scope

### Layout

`README.md` keeps, in this order and at roughly 150-200 lines:

1. Title and a purpose paragraph (what the launcher does, target versus host architecture).
2. `Support matrix`: one row per distribution, columns `Distribution`, `Releases`, `Modes`,
   `Source schemes`, `Memory floor (MiB)`, `Trust anchor`, `Example`, `Proof status`, `Guide`.
   Rows list only modes and example files present in the tree at merge time. The `Example`
   column is a plain cell so later issues (#123, #127-#129) add a file to a cell or add a row.
   A value the current documentation does not state reads `not stated`; RHEL's example cell
   reads `none shipped`.
3. `Choose a task` (anchor kept): the task table, now linking guides.
4. `Host and task prerequisites` (anchor kept): the existing table and private-storage
   paragraph, with links retargeted to guides.
5. `Quickstart`: five numbered steps (setup; launcher payload; verify release and prepare the
   profile; write and validate the manifest; build, then prove), each one sentence plus a link,
   with the commands they need already shown elsewhere linked rather than repeated.
6. `Development` (anchor kept): the existing section, including both help commands
   `.venv/bin/python scripts/iso_chain.py --help` and
   `.venv/bin/python scripts/iso_chain.py build --help` verbatim, so `CLIHelpTests` stays
   unchanged.
7. `Fedora installer launcher` (anchor kept): a two-line section linking
   `docs/guides/fedora.md`, so `docs/experiments/2026-09-08-static-launcher.md:64` resolves.
8. `Documentation`: links to the guides, the FTP runbook, ADRs, specs, experiments, AGENTS.md.

`docs/guides/` gains ten files. Each starts with an H1, a one-paragraph purpose, and ends with
one `Privacy and proof limits` section.

| File | Content moved from current README |
| --- | --- |
| `building-media.md` | offline validation, synthetic examples, initramfs and ISO builds on macOS, the build command |
| `sources.md` | source URL rules (incl. FTP userinfo grammar), `validate-external-source`, `serve-source`, FTP runbook link |
| `fedora.md`, `rocky.md`, `rhel.md`, `ubuntu.md`, `opensuse.md` | each distribution's section, plus its install-harness paragraphs |
| `presets.md` | reusable private blocks (heredoc verbatim), Rocky customization, Ubuntu reusable preset |
| `verification.md` | smoke proof, installed-disk menu and disk guards, installer evidence, unattended installation proof incl. xferlog grammar, JSON report schema |
| `target-bound-media.md` | target-bound media for hmcpctl incl. the media result fields |

Every distribution page uses exactly these H2 headings in this order: `Modes`,
`Example manifests`, `Verify the release`, `Prepare the profile`, `Memory floor`,
`Source tree and smoke stop point`, `Unattended installation`, `Proof status`,
`Privacy and proof limits`. A heading that has no content for a distribution keeps its place
with one sentence saying so (for example openSUSE `Unattended installation`: build refuses
login values unless every profile is Rocky/RHEL or every profile is Ubuntu, so openSUSE has
no unattended mode).

### Move rules

- Prose moves verbatim except: links retargeted to the new location; "above"/"below" cross
  references replaced by explicit links; a paragraph split where one half is generic and the
  other distribution-specific; and per-guide consolidation below.
- The four contract restatements (FTP userinfo grammar, JSON report schema, xferlog grammar,
  media result fields) move whole into their guide, and each gains a link to its governing
  record (ADR 0027, ADR 0030, `2026-10-27-ftp-install-evidence-design.md`, ADR 0015). They
  are not shortened.
- The preset heredoc (current `README.md:326-344`) moves byte-for-byte into `presets.md`.
- Consolidation: a sentence is removed only when its whole content is the generic rule now in
  that guide's `Privacy and proof limits` section (`umask 077`, fresh output paths, private
  manifests/media/source trees/evidence, QEMU is not native PowerVM, checks do not build or
  boot media). A sentence carrying a specific obligation (publication-directory access,
  verify with the media-building commit, an account or log rule) stays in place.
- Matrix and proof-status cells cite only facts stated in the moved prose or in a linked
  experiment's recorded result, naming QEMU or PowerVM for each.
- `AGENTS.md` and `docs/ftp-operator-runbook.md` change link targets only. ADRs, specs other
  than this one, plans and experiment records are not edited.

### Failure model

1. Actors and deployments: operators and contributors reading the rendered Markdown on GitHub
   or in a checkout; CI running `just check` on Linux and macOS.
2. Invariants and assets at stake: every safety, privacy and contract statement in the current
   README survives in exactly one guide or the README; inbound anchors from `AGENTS.md`, the
   runbook and the frozen experiment record resolve; `CLIHelpTests` strings stay in README;
   no matrix cell states a fact absent from the sources.
3. Accepted failure classes: links from outside this repository (bookmarks, issue comments)
   to removed README anchors stop resolving; bounded cost, the README `Documentation` and
   `Choose a task` sections route readers to the guides. Committed plans that cite old README
   line numbers become historical; plans are transient records.
4. Covered elsewhere: example manifests and their tests (#123, #124, #126); operator-file
   configuration (#122, #125, #127-#130); QEMU proof (#131); PowerVM/HMC (#6). Link and anchor
   validity is held by rumdl MD051/MD057 in `just check-markdown`.

## Success

- README is at most 200 lines, has the sections above, and every link resolves.
- The ten guides exist with the stated content; the five distribution pages have identical H2
  sequences.
- Every non-blank line of current `README.md:110-1206` appears in a guide, or is accounted for by
  a move rule above (retargeted link, explicit cross-reference, split, consolidation).
- `just check` exits 0.

## Validation

- Links and anchors: `Mode: focused-test` — `just check-markdown` (rumdl MD051/MD057); red
  observation by temporarily pointing one guide link at a missing anchor; green exit 0.
- Help commands: `Mode: focused-test` — `.venv/bin/python -m unittest -v
  tests.test_iso_chain.CLIHelpTests`; red by temporarily deleting one help line; green OK.
- Identical distribution shape: `Mode: focused-test` — the plan's one-off heading comparison
  command; red by renaming one heading; green prints nothing.
- Prose preservation and matrix facts: `Mode: task-test-not-applicable` — human-readable
  Markdown with no executable consumer; the plan's one-off line-accounting command lists moved
  lines for the author to account for, and review checks each matrix cell against its source.
