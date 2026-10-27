# FTP installation and residue evidence design

Issue #70; parent #37 Expected item 3. Authority: the approved four-profile operational
scope recorded in issue #70's `WORK:SCOPE` annotation, token `q70-7c180eb7`.

## Problem and scope

The earlier [FTP assessment](../../experiments/2026-10-02-authenticated-ftp-sources.md)
bypassed the launcher and did not inspect installed disks. This experiment uses the existing
CLI, launcher and canonical installation verifiers unchanged. No ownership transition,
caller migration, new runtime interface, ADR or compatibility path is needed.

The bounded subjects are Fedora 44, Rocky 9.8 and Ubuntu 26.04.1 unattended installation,
and openSUSE Leap 15.6 interactive readiness, under QEMU pSeries POWER9 on x86_64 Linux.
Native PowerVM belongs to #37/#72. The operator owns FTPS, residue fixes, openSUSE beyond
readiness and RHEL expansion; verifier implementation belongs to merged #77.

## Execution and success

Prepare current launcher assets from a recorded clean commit. Validate each source profile's
size/digest pins and original signed anchors using the existing preparation recipes. Build
fresh media for each arm with a fresh read-only FTP account in the digest-bound manifest.
Use generated high-entropy passwords, a private FTP chroot and untouched standard xferlog,
refusing anonymous and writes. Revoke accounts after each arm, including interruptions.
Record media, manifest, launcher and source identities. Use fresh disks, private per-arm
accounts, ports, consoles and captures, existing timeouts and checked resource availability.
After the Fedora arm, independent remaining arms may overlap within that resource budget.

For each unattended arm, collect the complete same-run canonical evidence set and run the
matching `verify-*-install-evidence` with the commit that built the media. A passing process
alone is insufficient. Record openSUSE's launcher markers, FTP transfers and visible YaST
readiness separately; no canonical FTP readiness-verifier claim is made.

Inspect each installed filesystem read-only, including hidden files, installer logs,
compressed logs and the boot filesystem, for the account and password in exact decoded and
canonical percent-encoded forms. List every matching path and representation, or none,
and separately report raw-image matches without inventing a filesystem path. Report the
inspection tool, reachable filesystem coverage and unreadable/unsupported areas. Count
console credential occurrences using a documented normalization and matching method.

Publish one dated experiment with per-arm results, canonical verification outcomes, residue
paths and evidence digests; add its AGENTS.md citation. Replace credential, account, host,
network and lab identifiers with consistent anonymous tokens. Raw artifacts remain private.
Failures remain failures; investigate them and report runtime defects before changing code.

## Failure model

- Actors and deployments: one authorized local operator, private read-only FTP server,
  emulated pSeries POWER9 guests; the public repository receives redacted prose only.
- Invariants and assets at stake: credentials and host identity remain private; evidence
  binds actual media and same-run artifacts; existing disks and source inputs are unchanged.
- Accepted failure classes: emulation may time out or fail; bounded retries are recorded
  and cannot substitute for a passing canonical proof. No native-hardware inference is made.
- Covered elsewhere: existing manifest/media validators and runtime guardrails enforce their
  contracts; #37/#72 own PowerVM, and the operator owns residue remediation.

## Validation

The experiment and citation use `task-test-not-applicable`: these are human-readable measured
observations with no executable consumer, so prose snapshots cannot verify them. The proof
is the actual four-arm execution and read-only residue inspection above. Run repository
Markdown, whitespace and secrets guardrails, mandatory commit hooks and hosted CI; review
public text against the private credential set before publication. No source behavior changes.
