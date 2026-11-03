# ADR 0035: Extend JSON Reports to the Remaining Commands

## Status

Accepted (2026-11-03) — reviewed contract for #152 and #153 under epic #150; not implemented.
Extends [ADR 0030](0030-report-validation-as-json.md).

## Context

ADR 0030 gave eight validation commands an opt-in `iso-chain-report-v1` report. Epic #150 asks
the same of the remaining commands and an offline description of the README task chooser and
prerequisite map. Those commands differ from the eight in four ways the code makes concrete:
`build` and `inspect` already own stdout (ADR 0015's `iso-chain-media-v1` line, or the canonical
manifest); `container-build`, `container-prepare-initramfs` and `smoke` replace the process with
`os.execvp`, so nothing runs after the child to report; `serve-source` serves until a signal; and
the preparation commands start `xorriso` or `dracut` with stdout inherited, so child output would
precede any report on stdout. `validate-external-source` prints unversioned JSON whose
`profile` value is a manifest key. Epic #81 named a doctor command as a non-goal, and #82
improved argparse "without adding a command registry".

## Decision

- **Widened set.** Add the existing subcommand-local `--json` to `prepare-fedora-source`,
  `prepare-rocky-source`, `prepare-rhel-source`, `prepare-opensuse-source`,
  `prepare-ubuntu-source`, `prepare-initramfs`, `install-fedora`, `install-rocky`,
  `install-ubuntu` and `validate-external-source`. Each emits one `iso-chain-report-v1` object
  on completion with ADR 0030's stdout, exit, usage, privacy and no-progress rules; stderr
  changes as the child-stdout bullet below states.
- **Refused set.** `build`, `container-build`, `container-prepare-initramfs`, `smoke`, `inspect`
  (with or without `--result`) and `serve-source` gain no `--json`; argparse rejects it through
  the existing text usage path, as ADR 0030 already does for commands outside its set. Their
  stdout stays byte-identical.
- **No successor version.** No widened command needs a field the v1 envelope lacks. The keys,
  types and four error categories stay as ADR 0030 defined them; only the `command` and `checks`
  vocabularies grow, which v1 consumers already dispatch on by `command`.
- **Child stdout.** In JSON mode, every child process a widened command starts with inherited
  stdout instead binds its stdout to the process's stderr, following `build`'s `grub2-mkrescue`
  precedent. Text mode keeps inherited stdout. In JSON mode stderr may therefore carry child-tool
  output; it is diagnostic, not part of the report contract.
- **External source.** `validate-external-source --json` reports `checks: ["source"]` in the v1
  envelope and omits the per-artifact list and profile name. The default output stays the
  existing unversioned object, byte for byte.
- **Describe.** Add an offline `describe` subcommand that always prints one
  `iso-chain-describe-v1` JSON object holding the task chooser and prerequisite map from one
  static table in `scripts/iso_chain.py`. It reads no host state, runs no subprocess, opens no
  file or socket and writes nothing, so it is not a doctor command. Its table does not build the
  parser or drive dispatch, so it is not a command registry.

Specification:
[JSON reports for the remaining commands](../workflow/specs/2026-11-03-json-reports-remaining-commands-design.md).

## Consequences

- Automation reads one report from each preparation, initramfs and install run instead of
  inferring success from an empty stdout and an exit status.
- Refused commands keep exit status as their machine signal; hmcpctl keeps reading
  `iso-chain-media-v1`. A smoke or container run cannot be reported without supervising the
  child instead of replacing the process, which this ADR does not do.
- JSON-mode stderr is no longer empty for commands that start children. Child output may name
  private paths, as it does in text mode today; the report itself still carries no input.
- `prepare-rhel-source` prints its `digest-source: mirror-sha256sum` line only in text mode; the
  JSON report implies it through `command`, because the flag is mandatory.
- The external-source report proves the same thing as the default output: each pinned artifact
  of the selected profile matched its manifest size and SHA-256. Consumers already hold those
  values in the manifest.
- `describe` adds a second versioned JSON family. The README tables and the table must not drift;
  #153 chooses whether the README is generated or compared and adds the failing test.

## Considered & rejected

- **Accept `--json` on `build` and `inspect` and print nothing extra.** judgment: fit; a flag that
  changes nothing invites consumers to expect a v1 report where the media line or manifest is.
- **Wrap the `iso-chain-media-v1` line inside a v1 report.** judgment: fit; ADR 0015 fixes that
  stdout byte for byte and hmcpctl reads it.
- **Supervise `smoke` and the container commands instead of `os.execvp`.** judgment: cost; it
  changes signal delivery, exit status and terminal ownership for interactive QEMU and container
  runs to gain a report that the exit status already gives. `smoke`'s console stdout is also
  `verify-log`'s input.
- **Forward `--json` into the container's `prepare-initramfs`.** judgment: fit; the engine shares
  that stdout and its own messages are outside this tool's control.
- **A startup report from `serve-source`.** judgment: fit; a ready-to-serve object is a progress
  event, which ADR 0030 rejects, and a completed report never comes.
- **Route child stdout to stderr in text mode too.** judgment: scope; simpler, but it changes
  default-mode streams, which this work keeps unchanged.
- **Discard child output in JSON mode.** judgment: fit; keeps stderr empty but drops `dracut` and
  `xorriso` diagnostics that the operator needs after a failure.
- **`iso-chain-report-v2` with the artifact list for `validate-external-source`.** judgment: fit;
  the list repeats manifest pins by construction and the profile name is a manifest key, which
  ADR 0030 keeps out of reports.
- **Replace the default `validate-external-source` output with a versioned object.**
  judgment: scope; it breaks existing parsers of an unchanged default interface.
- **`describe` as `--json` on each command, or reading README at run time.** judgment: fit; help
  stays human text, and parsing README couples a JSON contract to Markdown layout and needs the
  file read that the offline rule forbids.
- **A command registry that builds `parser()` and `describe` from one table.** judgment: scope; #81
  and #82 excluded it, and `describe` needs only task and prerequisite data.
