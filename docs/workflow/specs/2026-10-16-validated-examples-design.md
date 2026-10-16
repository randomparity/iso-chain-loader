# Parser-validated installation examples

## Problem

Issue #85 needs complete synthetic inputs readers can validate offline before adapting them.
The existing `validate-config` command and ADR 0029 own validation; no policy moves are needed.

## Scope

Ship six JSON manifests under `examples/`: `fedora.json`, `rocky-interactive.json`,
`opensuse-interactive.json`, `ubuntu-interactive.json`, `rocky-unattended.json`, and
`ubuntu-unattended.json`. Fedora uses the existing Kickstart fixture's media-path shape.
Also ship `target.json` and `base.json` illustrating the existing Rocky target/base input form.
Use documentation-only IPv4 addresses, a locally administered synthetic MAC, an example-domain
HTTPS source, visibly synthetic artifact sizes/digests, and a public test key without deployed
identity in keyed manifests. No credentials, real network assignments, or private keys ship.

README links each worked distribution sequence to its files. Explain copying `profile.json`
into `profiles.<name>`, matching `selected_profile` to that name, replacing source/network and
pins with operator values and verified `prepare-*` output, and retaining the Fedora Kickstart
media path relative to `--profiles`. Document the target distribution-release selector versus
the base profile-map key and provide both offline validation invocations.

A single focused test class in `tests/test_iso_chain.py` consumes the shipped bytes through the
real CLI with an empty PATH, captures status/streams, and checks no local artifacts appear.
It asserts the six intended distribution/login modes and exercises target/base composition.
Representative edits reject a missing selected profile, an invalid artifact digest, a missing
login-key partner, and an unmatched target selector. Do not duplicate parser rules.

Exclusions approved by the operator on 2026-10-16: validator/build behavior (#83), JSON (#86),
general CLI help (#82), real media/authenticated pins/boot proof (existing target workflows),
composition tooling and new profiles (separate approved scope). No ADR or migration is needed.

### Failure model

- Actors/deployments: readers adapting repository examples; offline development and CI hosts.
- Preserve: existing validation ownership, no external work, privacy and installation contracts.
- Accept: synthetic pins cannot fetch/build/boot; these are structural fixtures, stated plainly.
- Other owners: #83 owns validator behavior; existing target workflows own actual media proof.

## Success

The six named manifests and target/base pair pass the shipped validator from their own bytes.
Tests distinguish six modes and reject the four specified invalid edits deterministically.
README explains adaptation and proof limits and links the applicable worked sequences.
No runtime CLI, schema, recipe, dependency, or profile is added.

## Validation

- Mode: focused-test. `tests.test_iso_chain.ExampleConfigurationTests` checks shipped inputs,
  mode identity, target/base composition, rejection edits, exit codes and no created outputs.
  Red: a deliberately invalid shipped digest fails the positive-input case; restore afterward.
  Green: `.venv/bin/python -m unittest -v tests.test_iso_chain.ExampleConfigurationTests`.
- Mode: task-test-not-applicable. README adaptation/proof-limit prose requires reader review;
  wording snapshots cannot establish that an operator understands replacement or proof limits.
- Run `just check` before shipping; run focused Markdown/lint checks during edits.
