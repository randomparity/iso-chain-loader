# Task-Focused Documentation Implementation Plan

**Goal:** Move the operator manual out of `README.md` into ten guides under `docs/guides/` and
reduce README to purpose, support matrix, prerequisites, quickstart, development and links.

**Architecture:** Prose moves between Markdown files; nothing executable changes. Guides are
created first while the old README still stands, then README is rewritten and inbound links
retargeted, so every commit keeps `just check-markdown` green.

**Tech stack:** Markdown checked by rumdl 0.2.66 (`pyproject.toml` `[tool.rumdl]`), stdlib
`unittest` for `CLIHelpTests`.

Expected implementation size: 2,300–2,600 changed lines (L) — insertions plus deletions from the
file map: about 1,250 guide lines added, about 1,050 README lines removed and 180 written, and
under 20 link lines in AGENTS.md and the runbook.

## Global Constraints

- Spec: `docs/workflow/specs/2026-10-29-task-focused-documentation-design.md`. Its Layout, Move
  rules and Failure model bind every task.
- Markdown: 100-column lines (tables and code blocks exempt), rumdl owns formatting
  (`just fix` may reflow), no trailing whitespace.
- Line references below are to `README.md` at `origin/main` commit `30acf8c` (read it with
  `git show 30acf8c:README.md`).
- Do not edit `docs/adr/`, `docs/experiments/`, other specs or plans, `scripts/`, `tests/`,
  `examples/` or `assets/`. `AGENTS.md` and `docs/ftp-operator-runbook.md`: link targets only.
- Guardrails: `just check-markdown` per task; `just check` before the final commit; the commit
  hook runs `.venv/bin/pre-commit` (no tests). Never bypass a red gate.
- Relative links from `docs/guides/*.md`: README is `../../README.md`, ADRs `../adr/…`, specs
  `../workflow/specs/…`, experiments `../experiments/…`, examples `../../examples/…`, assets
  `../../assets/…`, runbook `../ftp-operator-runbook.md`.

## File map

| File | Change | Owns after the change |
| --- | --- | --- |
| `docs/guides/building-media.md` | create | offline validation, example adaptation, launcher payload and ISO builds |
| `docs/guides/sources.md` | create | source URL rules, pin validation, local serving, FTP pointer |
| `docs/guides/verification.md` | create | smoke proof, disk guards, installer evidence, install proof, JSON reports |
| `docs/guides/target-bound-media.md` | create | hmcpctl request/publication/result |
| `docs/guides/presets.md` | create | block/system composition, Rocky and Ubuntu presets |
| `docs/guides/{fedora,rocky,rhel,ubuntu,opensuse}.md` | create | per-distribution sequence, nine fixed H2 sections |
| `README.md` | rewrite | quickstart, matrix, prerequisites, development, links |
| `AGENTS.md` | link targets | unchanged prose |
| `docs/ftp-operator-runbook.md` | link targets | unchanged prose |

No caller migration beyond the inbound links listed in Task 2; no compatibility path except the
retained README anchors `#choose-a-task`, `#host-and-task-prerequisites`, `#development`,
`#fedora-installer-launcher` (inbound links from AGENTS.md and the frozen experiment record).

## Task 1: Create the ten guides

**Files:** create the ten `docs/guides/*.md` files above. README stays unchanged in this task.

**Interfaces:** Task 2 links these exact files and these anchors: `verification.md`
`#installer-smoke-proof`, `#unattended-installation-proof`, `#json-reports-for-validation-and-verification`;
`building-media.md` `#validate-configuration-offline`, `#synthetic-configuration-examples`,
`#building-the-launcher-initramfs-on-macos`, `#building-the-launcher-iso-on-macos`, `#build-the-iso`;
`sources.md` `#validate-source-pins`; `target-bound-media.md` (file only).

**Verification:**

- Links/anchors — `Mode: focused-test`. Command `just check-markdown`; red: temporarily change one
  guide link to `verification.md#no-such-anchor` and observe an MD051 error; revert; green exit 0.
- Identical distribution shape — `Mode: focused-test`. Expect exit 0 and no output from the
  command below; red: rename `## Memory floor` in `rhel.md`, expect a diff and exit 1; revert.

  ```sh
  set -o pipefail
  printf '## %s\n' 'Modes' 'Example manifests' 'Verify the release' 'Prepare the profile' \
    'Memory floor' 'Source tree and smoke stop point' 'Unattended installation' 'Proof status' \
    'Privacy and proof limits' > "$TMPDIR/q121-headings"
  for f in fedora rocky rhel ubuntu opensuse; do
    grep '^## ' "docs/guides/$f.md" | diff "$TMPDIR/q121-headings" - || exit 1
  done
  ```

- Heredoc verbatim — `Mode: focused-test`. Expect exit 0 from the command below; red: change one
  character inside the guide's heredoc, expect exit 1; revert.

  ```sh
  python3 - <<'PY'
  import subprocess, sys
  old = subprocess.run(["git", "show", "30acf8c:README.md"], capture_output=True, text=True,
                       check=True).stdout.splitlines(True)[325:344]
  sys.exit("".join(old) not in open("docs/guides/presets.md").read())
  PY
  ```

- Prose preservation — `Mode: task-test-not-applicable`: Markdown prose has no executable consumer.
  Run the sentence-accounting script in step 5 against the guides only and account for every
  listed sentence under a named spec move rule; README L1-29 is reviewed by hand in Task 2.

**Steps:**

1. Write each generic guide by moving these ranges (headings in brackets are the guide's H2/H3):
   - `building-media.md`: L110-142 [`Validate configuration offline`]; L264-307
     [`Synthetic configuration examples`]; L197-224 [`Building the launcher initramfs on macOS`];
     L144-195 [`Building the launcher ISO on macOS`]; L514-528 [`Build the ISO`].
   - `sources.md`: L479-489 from "An HTTP(S) `source` must be" [`Source URL rules`], adding a
     link to ADR 0026 and ADR 0027; L491-512 [`Validate source pins`]; a [`Serve a local tree`]
     section of one sentence linking `verification.md#installer-smoke-proof`, where `serve-source`
     stays; a two-sentence [`Authenticated FTP sources`] section linking the runbook, ADR 0016
     and ADR 0027.
   - `verification.md`: L532-569 [`Installer smoke proof`], opening with one prerequisites
     sentence linking `building-media.md#build-the-iso` (built ISO and the private run directory
     `PRIVATE`, created there by `umask 077` and `PRIVATE=$(mktemp -d)`); L571-600
     [`Installed-disk menu and disk guards`, H3]; L602-616 [`Installer evidence`, H3];
     L1076-1146 [`Unattended installation proof`], adding a link to
     `../workflow/specs/2026-10-27-ftp-install-evidence-design.md` after the xferlog grammar;
     L226-262 [`JSON reports for validation and verification`].
   - `target-bound-media.md`: L1005-1071 (H1 `Target-bound media for hmcpctl`).
   - `presets.md`: L312-353 [`Reusable private blocks`]; L355-405 [`Rocky customization`];
     L726-782 [`Ubuntu reusable preset`].
2. Write each distribution page with the nine H2 headings in order: `Modes`,
   `Example manifests`, `Verify the release`, `Prepare the profile`, `Memory floor`,
   `Source tree and smoke stop point`, `Unattended installation`, `Proof status`,
   `Privacy and proof limits`:
   - `fedora.md`: Modes L413-424; Examples L410-411; Verify L426-450; Prepare L452-472 and
     L474-479 (through "the launcher never falls back to another."), then a link to
     `sources.md#source-url-rules`; Memory floor: "No Fedora memory floor is stated. The
     unattended proof runs `install-fedora --memory-mib 32768`."; Source
     tree: link `verification.md#installer-smoke-proof`;
     Unattended L1148-1154 plus a link to `verification.md#unattended-installation-proof`;
     Proof status L1195-1206 plus links to `2026-10-01-powervm-iso-carried-kickstart.md`,
     `2026-10-17-powervm-cas-reboot.md` and `2026-10-27-ftp-installs-and-residue.md`. Every
     Proof status entry on every page is either the record's title, environment (QEMU or
     PowerVM) and link, or a summary of its Result qualified by its Proof limits or Boundary
     section; never a Result claim without those limits.
   - `rocky.md`: Modes L791-797; Examples L787-789; Verify L799-814; Prepare L816-830; Memory
     L832-837; Source tree L839-848; Unattended L850-873 and L1156-1182; Proof status from
     `2026-10-02-rocky-installer.md`, `2026-10-02-rocky-unattended-install.md`,
     `2026-10-04-rocky-completion-marker.md`, `2026-10-26-rocky-preset-install.md`, FTP record.
   - `rhel.md`: Modes L878-889; Examples "No RHEL example manifest ships yet."; Verify L894-912;
     Prepare L914-927; Memory L929 first sentence; Source tree L929-932 remainder; Unattended
     L890-892; Proof status from `2026-10-15-rhel-installer.md`.
   - `ubuntu.md`: Modes L625-635; Examples L621-623; Verify L637-649; Prepare L651-663; Memory
     L665-668; Source tree L670-694; Unattended L696-724 and L1184-1193; Proof status from
     `2026-10-02-ubuntu-installer.md`, `2026-10-03-ubuntu-unattended-install.md`,
     `2026-10-26-ubuntu-preset-install.md`, FTP record.
   - `opensuse.md`: Modes L940 and L983-987; Examples L937-938; Verify L941-962; Prepare L964-975;
     Memory L977-981; Source tree L987-1000; Unattended: build refuses login values unless every
     profile is Rocky/RHEL or every profile is Ubuntu (L1033-1036), so openSUSE has no unattended
     mode; Proof status from `2026-10-02-opensuse-installer.md`,
     `2026-10-04-opensuse-btrfs-installed-disk.md`, FTP record.
3. In every guide replace each reference to content now in another file with an explicit link:
   "above", "below", "as shown for", "as for <distro>", "as with <distro>", "the same
   arguments", "in another shell", "keep the HTTP server running", "its section". Find them with:

   ```sh
   rg -n -i 'above|below|as shown for|as for|as with|same arguments|another shell' docs/guides
   rg -n -i 'keep the HTTP|its section' docs/guides
   ```

   A guide that uses `$PRIVATE` before defining it links `building-media.md#build-the-iso` in
   the sentence before its first use. Retarget README-internal links to the new file and anchor.
4. Give every guide one closing `Privacy and proof limits` section restating, once, the generic
   rules of the spec's consolidation rule; remove only sentences wholly covered by it.
5. Run the sentence-accounting script, saved outside the repository (scratch directory). It
   joins each file's prose, collapses whitespace, splits at sentence ends and prints every old
   README:110-1206 sentence absent from the guides:

   ```python
   import pathlib, re, subprocess


   def sentences(text):
       return {s for s in re.split(r"(?<=[.:;])\s+", " ".join(text.split())) if len(s) > 3}


   old = subprocess.run(
       ["git", "show", "30acf8c:README.md"], capture_output=True, text=True, check=True
   ).stdout.splitlines()[109:]
   new = " ".join(" ".join(p.read_text().split()) for p in pathlib.Path("docs/guides").glob("*.md"))
   for sentence in sorted(sentences("\n".join(old))):
       if sentence not in new:
           print(sentence)
   ```

   Expected: only sentences changed by a named spec move rule (retargeted link, explicit
   cross-reference, split with both halves present, consolidated generic sentence). Record each
   with its rule in the commit message body; restore any other listed sentence.

6. Run `just check-markdown` (expect exit 0) and the heading and heredoc commands above.
7. Commit: `docs: add task guides under docs/guides`.

## Task 2: Rewrite README and retarget inbound links

**Files:** modify `README.md`, `AGENTS.md`, `docs/ftp-operator-runbook.md`.

**Interfaces:** consumes the Task 1 files and anchors listed in Task 1's Interfaces block.

**Verification:**

- Links/anchors — `Mode: focused-test`. `just check-markdown`; red: temporarily remove the README
  `Fedora installer launcher` heading and observe MD051 for
  `docs/experiments/2026-09-08-static-launcher.md`; restore; green exit 0.
- Help commands — `Mode: focused-test`.
  `.venv/bin/python -m unittest -v tests.test_iso_chain.CLIHelpTests`; red: temporarily delete the
  `build --help` line, expect `test_documented_help_commands_are_safe_entry_points` to fail;
  restore; green `OK`.
- README size — `Mode: focused-test`. `wc -l < README.md`; expect at most 200.
- Matrix facts — `Mode: task-test-not-applicable`: a human-read table with no executable
  consumer; each cell is checked against the guide or experiment it cites.

**Steps:**

1. Rewrite `README.md` with the spec's eight sections in order. Keep L30-50 (prerequisites) and
   L52-108 (Development) verbatim apart from retargeted links. The matrix rows:
   - Fedora: 44; Kickstart carried on the ISO (unattended fixture); memory `not stated`; signed
     `CHECKSUM` (Fedora release key); `examples/fedora.json`.
   - Rocky: 9.8; interactive, keyed unattended, preset `rocky-9.8-minimal` r1; 6400; signed
     `CHECKSUM` (Rocky 2022 key); interactive, unattended, target/base and preset examples.
   - RHEL: 9.0-9.8, 10.0-10.2; interactive, keyed unattended; 6400 (Rocky's, until measured);
     unsigned mirror `SHA256SUM`; `none shipped`. Proof status says the interactive PowerVM
     record covers 9.8 and 10.2 only and that unattended RHEL is not yet exercised by an install
     harness or verifier (#97); `rhel.md` `Proof status` says the same.
   - Ubuntu: 26.04.1; interactive, keyed unattended, preset `ubuntu-26.04.1-server` r1; 5888;
     signed `SHA256SUMS` (Ubuntu CD image key); interactive, unattended and preset examples.
   - openSUSE: Leap 15.6; interactive; 6400; signed `CHECKSUMS` (openSUSE key, expired
     2026-06-19); `examples/opensuse-interactive.json`.
   - Source schemes: from `docs/guides/sources.md#source-url-rules` (moved L479-489), state
     `https`; `http` (loopback/RFC 1918 IPv4); `ftp` with userinfo, linking that section once and
     noting once that installer escape and path handling over FTP stay unproven (#70). Proof
     status cells follow the guides' Proof status sections, limits included.
2. Retarget: `AGENTS.md` L31 `README.md#fedora-installer-launcher` → `docs/guides/fedora.md`;
   runbook L4 → `guides/target-bound-media.md`, L48 and L107 →
   `guides/verification.md#unattended-installation-proof`, L106 →
   `guides/verification.md#installer-smoke-proof`. Change nothing outside the link targets. Keep
   AGENTS L12-13, L132, L138 and runbook L3 (README anchors retained). Per the operator's 2026-10-29
   decision, reword only the "the README('s)" phrases at runbook L35, L47, L68, L89, L106 and
   AGENTS L13 to name the guide.
3. Run `rg -n -i 'above|below|as shown for|as for|as with' README.md` and replace each hit whose
   target left README (for example "as described below" in the prerequisites table) with a
   link. Re-run the Task 1 sentence-accounting script; expect no new unaccounted sentences. Review the
   README L1-29 rewrite by hand: the purpose paragraph keeps every distribution and mode, and
   the runbook-before-FTP sentence (L27-28) stays in `Choose a task`.
4. Run `just check` (expect exit 0) and the CLIHelpTests command.
5. Commit: `docs: reduce README to a quickstart and support matrix`.
