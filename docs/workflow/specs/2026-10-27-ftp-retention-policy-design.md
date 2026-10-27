# Retain observed installer FTP history

Issue #117; operator decision 2026-10-27. Governing decision:
[ADR 0016](../../adr/0016-assess-authenticated-ftp-sources.md), dated amendment.

## Problem

The [QEMU experiment](../../experiments/2026-10-27-ftp-installs-and-residue.md) found
plaintext FTP account values in root-owned mode `0600` installer files after Fedora 44,
Rocky 9.8 and Ubuntu 26.04.1 installations. The runbook leaves sanitization undecided.

## Scope and design

Amend ADR 0016's Status section by date, preserving the historical assessment body.
The amendment owns the policy; the existing runbook consumes it by reference. No ownership
transition, caller migration, runtime path or interface change is required. ADR 0027's
protocol and evidence decisions remain unchanged; no amendment there is needed.

Record the approved choice: accept this observed root-only history after immediate per-run
account revocation and session termination, retaining disks and copies privately under the
lab's retention policy. Mandatory media cleanup remains. Require no automated guest-file
deletion. Revocation bounds account use; root-only permissions restrict ordinary local access,
not privileged readers or historical bytes. Neither control proves erasure or disk-release safety.

Alternatives are bounded guest-file sanitization and secure erasure. The operator selected
retention; implementing deletion adds separately authorized work and would not establish
historical-byte erasure. Keeping the decision implicit would leave the requested policy unsettled.
No runtime code, installer hooks, verification tools, raw artifacts or historical experiments change.
No new numbered ADR, retention duration, release policy or credential-channel redesign is introduced.

## Success

1. ADR 0016 records the selected policy, rationale and residual risk without rewriting history.
2. The runbook applies that decision while retaining immediate revocation, session termination,
   mandatory media cleanup and private disk/copy retention under lab policy.
3. Both changed operator documents bound acceptance to the observed Fedora 44, Rocky 9.8 and
   Ubuntu 26.04.1 QEMU results; no claim covers RHEL, installed openSUSE, escaped-userinfo
   interoperability or native PowerVM. No deletion implementation or disk-release guarantee appears.

## Failure model

- Actors and deployments: lab operator using the existing FTP runbook; observed QEMU pSeries/POWER9
  installs of Fedora 44, Rocky 9.8 and Ubuntu 26.04.1.
- Invariants and assets: truthful scope/evidence, private credential-bearing disks/copies, mandatory
  media cleanup, immediate account revocation and termination of authenticated sessions.
- Accepted failure classes: retained observed plaintext installer history after revocation, by
  explicit operator choice; historical raw bytes remain, with no erasure or release-safety claim.
- Covered elsewhere: runtime sanitization/hooks/tools — operator, separately authorized work;
  secure erasure — operator/storage owner; channel redesign, FTPS, fallback and provisioning —
  operator, separate architecture decision; added profile/platform proof — operator (#37/#72 for
  native PowerVM); retention duration and disclosure/release policy — operator/lab owner.

## Threat model

- Boundary inventory: no added or widened executable boundary. Existing plaintext FTP, privileged
  guest-file access and private artifact storage remain the relevant operational boundaries.
- Actor model: trust the operator/storage owner to retain private copies and revoke accounts;
  on-path observers can read credentials/content; privileged disk readers can read retained history.
- Control per boundary: preserve the runbook's fresh scoped read-only account, immediate revocation
  and session termination, owner-only evidence/copies and mandatory media cleanup. No new control
  against on-path substitution or privileged historical-byte access is claimed.
- Explicitly out of scope: sanitization/secure erasure, channel redesign and extra proof, owned as
  above. Acceptance supplies no disclosure/release authorization and does not generalize profiles.

## Validation

The implementation plan inventories the policy and guidance contracts as human-readable decisions;
no executable consumer validates their wording. Review the documents against the approved decision
and cited observations. Run Markdown, whitespace, secrets and the six-recipe precommit checks.
No runtime behavior changes; no local full test suite, media build or QEMU rerun is applicable.
