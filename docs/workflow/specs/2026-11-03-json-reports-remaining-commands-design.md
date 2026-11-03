# JSON reports for the remaining commands

Status: accepted contract (2026-11-03); not implemented.
Scope: #151, under epic #150. Decision: [ADR 0035](../../adr/0035-extend-json-reports-to-the-remaining-commands.md).
Extends the [JSON validation reports](2026-10-16-json-validation-reports-design.md) design, whose
rules apply unless this document says otherwise. Implementation: report widening in #152 and
`describe` in #153. Line references are to `scripts/iso_chain.py` at 4c59e72.

## Problem and scope

Automation can read `iso-chain-report-v1` from eight commands only (`JSON_COMMANDS`, :4119).
The other sixteen print nothing on success, print a media or manifest line, replace the process,
or print unversioned JSON. The README task chooser and prerequisite map exist only as Markdown.
This design fixes, for every remaining command, whether `--json` is accepted and what it emits,
and the shape of an offline description command. It changes no code, default output, help text,
evidence format, error category or `iso-chain-media-v1` byte. A doctor command and a command
registry stay excluded (#81, #82); progress events stay rejected (ADR 0030).

## Command contract

| Command | `--json` | Successful `checks` | Child stdout in JSON mode |
| --- | --- | --- | --- |
| `prepare-fedora-source`, `prepare-rocky-source`, `prepare-rhel-source` | accepted | `["preparation"]` | `xorriso` extraction (:2198) to stderr |
| `prepare-ubuntu-source` | accepted | `["preparation"]` | `xorriso` extraction (:2445) to stderr |
| `prepare-opensuse-source` | accepted | `["preparation"]` | starts no child |
| `prepare-initramfs` | accepted | `["preparation"]` | `dracut` (:2681) to stderr; `dracut --help` is already captured (:2615) |
| `install-fedora`, `install-rocky`, `install-ubuntu` | accepted | `["installation"]` | QEMU already writes to the console log (:2916); `qemu-img` is already captured (:3013) |
| `validate-external-source` | accepted | `["source"]` | starts no child |
| `build`, `inspect` | refused | not applicable | stdout owned by ADR 0015 or the canonical manifest; `inspect`'s `xorriso` (:2036) stays as it is |
| `container-build`, `container-prepare-initramfs`, `smoke` | refused | not applicable | process replaced by `os.execvp` (:1991, :2029, :2743) |
| `serve-source` | refused | not applicable | serves until a signal; no completion |

Each `checks` value is one atomic command check meaning that command's existing complete
contract, as `verification` does for verifiers. `preparation` covers its input checks, any
digest pins and no-replace publication of its output. `installation` covers the install
phase, the installed boot, the changed-disk check and publication of the result directory,
whose `result.json` stays the record of run details. `source` covers the size and SHA-256 check
of every pinned external artifact of the selected profile. A failure reports `[]`.

Widened commands join `JSON_COMMANDS`, so ADR 0030's argv rule recognizes JSON usage errors for
them unchanged: an exact command as the first token and a standalone `--json` before any `--`.
Refused commands reject `--json` through argparse's text usage error and exit 2, as every
command outside `JSON_COMMANDS` does today.

## Envelope and streams

The envelope stays `iso-chain-report-v1`: keys `version`, `command`, `outcome`, `checks`,
`error`; categories `usage`, `validation`, `external-tool`, `io`; `field` null except the
existing safe manifest schema paths. The exception table in the 2026-10-16 design applies
unchanged. A v1 consumer must treat an unrecognized `command` as unsupported rather than failed.
Categories follow where each command already translates failures: `install-*` turn QEMU and
`qemu-img` failures into `ValidationError` (`validation`); a missing `dracut` is a
`ValidationError`; a missing `xorriso` is an `OSError` (`io`); a nonzero `xorriso` or `dracut`
exit is a `CalledProcessError` (`external-tool`, child exit code). `install-*`,
`prepare-opensuse-source` and `validate-external-source` therefore never report `external-tool`.

Stdout carries exactly one report object plus newline and nothing else. In JSON mode:

- A widened command passes `stdout=sys.stderr` to each child it starts with inherited stdout.
  Text mode passes nothing, keeping inherited stdout and today's stream bytes.
- Stderr may carry child-tool output. It is diagnostic and unbounded by this contract; apart
  from the interruption line below, the tool writes none of its own prose there.
- `prepare-rhel-source` does not print `digest-source: mirror-sha256sum` (:2364); text mode still
  does.
- Signals keep today's behavior and give no report. SIGHUP or SIGTERM during `install-*` prints
  the fixed `error: interrupted by SIG...` line on stderr and exits 128 plus the signal number.
  Any other signal, and any signal during another widened command, ends the process by Python's
  default handling (for SIGINT, a traceback; otherwise death by the signal). An empty stdout with
  a nonzero exit means no report was produced.

## External source report

`validate-external-source --json` emits
`{"checks":["source"],"command":"validate-external-source","error":null,"outcome":"passed",`
`"version":"iso-chain-report-v1"}` (wrapped here). It omits the profile name, a manifest key, and
the artifact list, whose sizes and digests equal the manifest pins whenever the command passes.
An unreachable, redirected, oversized or mismatched source raises today's `ValidationError` and
reports category `validation` with field null. Without `--json`, the command prints today's
unversioned `{"artifacts":[...],"profile":...}` object byte for byte (:4998).

## Describe contract

`describe` takes no options beyond `--help` and always prints one canonical JSON object plus
newline on stdout, exit 0, with empty stderr. Canonical means UTF-8, sorted keys, separators
`(",", ":")`, `ensure_ascii=False`. Any argument is a text usage error, exit 2. It has no `--json`
flag and is not in `JSON_COMMANDS`.

```json
{"prerequisites":[{"commands":["build","container-build"],"details":["..."],"guides":[],"name":"Build an ISO"}],"tasks":[{"commands":["validate-config"],"details":["...","..."],"guides":["docs/guides/building-media.md#validate-configuration-offline"],"name":"Check a manifest offline"}],"version":"iso-chain-describe-v1"}
```

- `version` is `iso-chain-describe-v1`; a field change needs a new version.
- `tasks` holds one row per README "Choose a task" row and `prerequisites` one per "Host and task
  prerequisites" row, in README order.
- Every row has exactly `name` (the README first cell's text), `details` (one string per
  remaining cell, in order, with Markdown links reduced to their text and inline-code backticks
  removed), `guides` (each link target in the
  row, in order, as a repository-relative path; a README-local anchor such as `#development`
  becomes `README.md#development`) and `commands` (the subcommands the task uses, possibly
  empty).
- The data is one static table of frozen dataclasses or tuples in `scripts/iso_chain.py`. It
  feeds only `describe` and the README drift check; `parser()` and `main()` dispatch stay as
  written.
- `describe` reads no file, environment, `PATH` or host state, starts no process, opens no
  socket and writes no file. It reports what a task needs, never whether this host has it.

Tests in #153 must fail when a README row and its table row differ in name, details or
link targets, when a `commands` entry is not a real subcommand, and when `describe` touches
the file system, a subprocess or a socket. Whether README is generated from the table or only
compared with it is #153's choice.

## Ownership, compatibility and constraints

`parser()` and `main()` stay the dispatch and reporting owners; `_json_report` and
`_print_checks` serve the widened commands, extended with the new `checks` values. Command
functions keep their signatures; the child-stdout choice reaches them from `args.json`.
Default text output, help, evidence formats, `result.json`, `iso-chain-media-v1` and the
unversioned external-source object are compatibility paths kept unchanged. Python 3.14,
stdlib only, macOS arm64 and x86_64 Linux hosts and the ppc64le POWER9 target are unchanged.

## Failure model

- Actors and deployments: operators, CI and hmcpctl-adjacent automation on macOS or Linux
  running preparation, initramfs and QEMU install commands with private manifests and sources.
- Invariants at stake: stdout holds one report and nothing else; reports carry no input value;
  refused commands keep stdout byte-identical; text mode keeps today's streams.
- Accepted failure classes: signals, process termination and unwritable stdout give no report;
  a child that writes to its stderr in JSON mode is visible there; a child that ignores the
  stdout binding by opening `/dev/tty` is outside this contract.
- Covered elsewhere: ADR 0015 for media results, ADR 0030 for the envelope and categories,
  evidence verifiers for install truth, #153 for README drift.

## Threat model

- Boundary: private manifests, paths, source URLs and child output on one side; a shareable
  report on the other. No input acceptance, network reach or file authority widens.
- Controls: fixed command, check and category strings; no profile name, URL, path, digest or
  exception text in reports; `describe` emits only static repository text.
- Residual: JSON-mode stderr can show child output with private paths, exactly as text mode
  does; operators keep stderr private (`umask 077` storage).

## Success and validation

For #152: CLI subprocess tests per widened command for success where a fake child or loopback
source allows it, and for each failure category that command can reach, with privacy canaries
in paths, profile names, credentials and source URLs. A fake `xorriso` and `dracut` on a private
`PATH` that write to stdout prove stdout holds only the report in JSON mode and that text mode is
unchanged. Each refused command rejects `--json` with exit 2 and unchanged stdout. Byte
comparisons cover default text output and `validate-external-source`'s default object. For #153:
the drift and offline tests above. Prove new tests bite with a controlled fault. Neither issue
changes media or boot behavior, so media build and VM proof are not applicable. #152 also updates
the guide text this contract makes false: the JSON section of `docs/guides/verification.md`
(empty stderr, the eight-command list, unchanged `validate-external-source`) and
`docs/guides/rhel.md`'s statement that `prepare-rhel-source` prints its `digest-source` line.
