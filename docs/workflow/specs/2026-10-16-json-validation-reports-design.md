# JSON validation reports

Issue #86; parent #81; scope token `q86-8f5b160e`. Status: approved by the operator on 2026-10-16.
Decision: [ADR 0030](../../adr/0030-report-validation-as-json.md).

## Problem and scope

Automation needs a bounded report without interpreting verifier prose. Extend the existing
parser/main reporting boundary for `validate-config`, `verify-log`, `verify-launcher-log`,
`verify-pcap`, `verify-installer-evidence`, `verify-fedora-install-evidence`,
`verify-rocky-install-evidence` and `verify-ubuntu-install-evidence` only. Preserve the default
text paths, exit semantics, verifier dependencies, producer and evidence bytes, `inspect --result`
and `validate-external-source`. The offline interface belongs to #83; examples to #85; FTP
verifier repairs to #77; producer/evidence changes require separate approved scope.

## Contract

Add a subcommand-local `--json` boolean to those eight commands. Existing invocations remain
valid. A JSON request is recognized for parse errors only when argv's first token is an exact
supported command and a standalone `--json` occurs before the first `--` terminator. It may
appear before or after other subcommand options. No global flag or alternate spelling is added.
Other commands reject it through their existing text usage path. `--help` retains argparse's
human help, stdout and exit 0 even together with `--json`; help emits no JSON.

Normal JSON completion emits exactly one UTF-8 JSON object plus newline on stdout, sorted keys,
compact separators, `ensure_ascii=False`; stderr is empty. Fixed keys are `version`, `command`,
`outcome`, `checks`, `error`. Version is the string `iso-chain-report-v1`; command is the exact
supported subcommand; outcome is `passed` or `failed`. Unknown versions require a new consumer.
`error` is null on success; otherwise exactly `category` and `field`. No prose/message is emitted.
Categories are the closed strings `usage`, `validation`, `external-tool`, `io`.
`field` is null or a safe schema path recorded as structured metadata at a known validator.

`checks` is an array of completed **atomic command checks**, not a progress trace. On successful
`validate-config`, it is `["configuration", "renderability"]`; each successful verifier reports
`["verification"]`. `verification` means that command's existing complete verification contract,
including its operator-reviewed assumptions; it does not turn those assertions into measured
proof. Failure reports `[]`, even if some internal prerequisites completed. This deliberately
coarse guarantee avoids invented progress and changes to verifier policy. JSON consumers identify
the verification contract by `command`; README explains the existing proof limits.

| Failure boundary | Category | Exit |
| --- | --- | --- |
| argparse usage, missing/extra/invalid options | usage | 2 |
| ValidationError, including bounded malformed content and evidence rejection | validation | 2 |
| tcpdump launch, nonzero result or timeout already translated by verify_pcap | external-tool | 2 |
| uncaught CalledProcessError | external-tool | existing child code, or 1 for zero |
| uncaught OSError | io | 1 |
| malformed-content ValueError escaping a selected JSON command | validation | 2 |

Usage errors in an enabled JSON request emit the failed object on stdout and empty stderr,
without human usage text. ArgumentParser.error raises a private usage exception; ordinary text
parsing retains argparse's existing behavior. JSON parse handling and execution handling share
one response encoder. Disabled mode retains the existing exception text and streams byte for
byte, including tcpdump's validation exit 2. In JSON mode external captured stdout/stderr and
exception representations are discarded. Output write failures cannot guarantee a report;
BrokenPipeError/OSError while writing the report retain conventional failure behavior.

No codes come from exception text. Extend ValidationError with optional safe field metadata;
`_manifest_error` records a field only when it matches fixed manifest schema names and fixed path shapes.
Dynamic profile names, unknown keys and user values never enter that metadata: omit the field
(null) rather than sanitize a user-derived key. Preserve the metadata when validate_configuration
wraps its error. A narrow ValidationError subclass identifies tcpdump dependency failures at
verify_pcap's existing translation boundary; it changes neither callers nor text exceptions.
Other validators without existing structured field knowledge report null. No broad taxonomy is
introduced. The JSON boundary catches malformed-content ValueError without repairing adjacent
legacy build behavior (including the separately identified huge-JSON-integer case).

Synthetic success: `{"checks":["configuration","renderability"],"command":"validate-config",
"error":null,"outcome":"passed","version":"iso-chain-report-v1"}` (shown wrapped here).
Synthetic failure: `{"checks":[],"command":"verify-log","error":{"category":"validation",
"field":null},"outcome":"failed","version":"iso-chain-report-v1"}`.

## Ownership, compatibility and constraints

Keep parser()/main() as dispatch and reporting owners; validators remain semantic owners.
Direct Python callers keep their existing return values. No ownership migration or obsolete
path removal is needed; the protected default text interface remains as a compatibility path.
Python 3.14, stdlib-only runtime, macOS arm64 and x86_64 Linux development hosts, and ppc64le
POWER9 target remain unchanged. No runtime dependencies or toolchain changes.

## Failure model

- Actors and deployments: local operators and CI invoking the CLI on macOS/Linux with private
  configuration, logs, records and captures; input files and CLI arguments may be hostile.
- Invariants and assets at stake: versioned report bytes; private identifiers, credentials,
  source URLs, command lines and input content; truthful completed checks; legacy exits/streams.
- Accepted failure classes: process termination, interpreter startup failure, exhausted memory
  and inaccessible stdout cannot promise a complete report. Internal programming errors outside
  the declared ValidationError/ValueError/OSError/subprocess boundaries remain visible failures,
  not fabricated successful reports. Atomic checks intentionally omit partial internal progress.
- Covered elsewhere: evidence truth and native PowerVM proof retain existing evidence/experiment
  contracts; FTP repair #77; producer/evidence changes separate scope; legacy build integer
  handling separate follow-up. Existing input size caps and no-fallback rules remain binding.

## Threat model

- Added boundary: private exception/input state to public-shaped JSON output; no existing input
  acceptance or filesystem/network authority is widened.
- Actors: local callers control argv, configuration keys/values, file names, logs and records;
  reports are safe to share only because their fields are fixed metadata rather than input echoes.
- Controls: bounded static command/category/check values, schema-only field metadata, no exception
  messages or subprocess output; existing file size and semantic checks remain authoritative.
  Tests inject distinct canaries in paths, unknown keys, profile names, credentials and logs.
- Out of scope: compromised interpreter/dependencies, signals and resource exhaustion; no new
  trust in records, operator assertions or tcpdump beyond the existing verifier contract.

## Success and validation

For the eight named commands: JSON success and reachable declared failures match this closed
schema and preserve exits; default stdout/stderr bytes remain unchanged on equivalent inputs.
No raw input appears in JSON reports or enabled JSON error stderr. CLI tests cover malformed
JSON including large integers, missing/extra options, invalid profile, missing/oversized files,
evidence rejection, tcpdump absence/nonzero/timeout and successful verification fixtures.
Run actual subprocess CLI tests for successes and normal failures; a stdlib fake tcpdump placed
on a private test PATH exercises tool outcomes without dependencies or network. A mocked timeout
at subprocess.run may complement the real executable boundary without waiting 30 seconds.
Compare legacy result bytes and exercise inspect/producer/external-source regression tests.
Prove new tests bite with a controlled fault and revert it. Run focused unittest classes, lint,
format, Markdown/secrets gates, then worker-owned `just check` before shipping. CLI reporting
changes no media/runtime policy, so VM/media boot is not applicable.
